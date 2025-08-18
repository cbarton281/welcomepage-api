import os
import tempfile
import subprocess
import logging
from typing import Final
from fastapi import UploadFile, HTTPException
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log
from utils.logger_factory import new_logger
from utils.supabase_storage import upload_to_supabase_storage
from utils.short_id import generate_file_id

# FFmpeg settings for GIF conversion
MAX_FPS: Final[int] = 15
MAX_WIDTH: Final[int] = 320
PIXEL_FORMAT: Final[str] = "rgb24"

class WaveVideoService:
    """Service for processing wave video uploads and converting them to optimized GIFs."""

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(subprocess.CalledProcessError),
        before_sleep=before_sleep_log(new_logger("_convert_to_gif_retry"), logging.WARNING)
    )
    async def _convert_to_gif(self, input_path: str, gif_path: str) -> None:
        """Convert webm video to GIF using FFmpeg with retries.

        Args:
            input_path: Path to input webm file
            gif_path: Path where GIF should be saved

        Raises:
            subprocess.CalledProcessError: If FFmpeg conversion fails
        """
        ffmpeg_command = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-vf", f"fps={MAX_FPS},scale='min({MAX_WIDTH},iw)':-1:flags=lanczos",
            "-pix_fmt", PIXEL_FORMAT,
            gif_path
        ]
        
        result = subprocess.run(
            ffmpeg_command,
            check=True,
            capture_output=True,
            text=True
        )
        if result.stderr:
            log = new_logger("_convert_to_gif")
            log.warning(f"FFmpeg output: {result.stderr}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),  # Supabase client exceptions
        before_sleep=before_sleep_log(new_logger("_upload_gif_retry"), logging.WARNING)
    )
    async def _upload_gif(self, gif_content: bytes, filename: str) -> str:
        """Upload GIF to storage with retries.

        Args:
            gif_content: Binary content of the GIF
            filename: Target filename in storage

        Returns:
            str: Public URL of uploaded GIF

        Raises:
            HTTPException: If upload fails
        """
        return await upload_to_supabase_storage(
            file_content=gif_content,
            filename=filename,
            content_type="image/gif"
        )

    async def process_wave_video(self, video_file: UploadFile, user_public_id: str) -> str:
        """
        Convert an uploaded wave video to an optimized GIF and store it.

        Args:
            video_file: FastAPI UploadFile containing the webm video
            user_public_id: Public ID of the user for filename generation

        Returns:
            str: Public URL of the stored GIF

        Raises:
            HTTPException: If video processing or upload fails
        """
        log = new_logger("process_wave_video")
        log.info(f"Starting wave video processing for user {user_public_id}")
        if not video_file:
            raise HTTPException(status_code=400, detail="No video file provided")

        input_path = ""
        gif_path = ""
        try:
            # Save webm to temp file
            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
                content = await video_file.read()
                tmp.write(content)
                input_path = tmp.name
                gif_path = f"{input_path}.gif"

            # Convert video to GIF
            await self._convert_to_gif(input_path, gif_path)
            log.info("Successfully converted video to GIF")

            # Upload GIF to storage
            gif_filename = f"{generate_file_id(user_public_id)}-wave-gif.gif"
            with open(gif_path, 'rb') as gif_file:
                gif_content = gif_file.read()
                gif_url = await self._upload_gif(gif_content, gif_filename)
                log.info(f"Successfully uploaded GIF to storage: {gif_filename}")

            log.info(f"Successfully processed wave video for user {user_public_id}")
            return gif_url

        except subprocess.CalledProcessError as e:
            log.error(f"FFmpeg conversion failed: {e.stderr}")
            raise HTTPException(status_code=500, detail="Video conversion failed")
        except Exception as e:
            log.error(f"Error processing wave video: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to process video")
        finally:
            # Clean up temp files
            for path in [input_path, gif_path]:
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError as e:
                        log.error(f"Failed to remove temp file {path}: {e}")
