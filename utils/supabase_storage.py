import os
import re
import logging
from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from supabase import create_client, Client
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log
import httpx
import httpcore

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_BUCKET = "welcomepage-media"

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in environment variables.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

async def check_file_exists_in_storage(filename: str) -> bool:
    """
    Check if a file exists in Supabase Storage bucket by making a HEAD request.
    
    Args:
        filename: The filename/path to check
        
    Returns:
        True if file exists, False otherwise
    """
    try:
        # Get the public URL for the file
        url = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(filename)
        # Make a HEAD request to check if file actually exists
        import requests
        head_response = requests.head(url, timeout=5, allow_redirects=True)
        return head_response.status_code == 200
    except Exception:
        # If we can't check, assume it doesn't exist to be safe
        return False

async def delete_from_supabase_storage(filename: str) -> tuple[bool, bool]:
    """
    Delete a file from Supabase Storage bucket.
    
    Args:
        filename: The filename/path to delete
        
    Returns:
        Tuple of (success, file_existed):
        - success: True if operation succeeded (file deleted or didn't exist), False if error
        - file_existed: True if file actually existed and was deleted, False if file didn't exist
    """
    # First check if file exists before attempting deletion
    file_existed = await check_file_exists_in_storage(filename)
    
    try:
        res = supabase.storage.from_(SUPABASE_BUCKET).remove([filename])
        if hasattr(res, "error") and res.error:
            error_str = str(res.error).lower()
            # If file doesn't exist, that's okay - return success=True, file_existed=False
            if "not found" in error_str or "does not exist" in error_str:
                return (True, False)
            raise Exception(f"Supabase deletion failed: {res.error}")
        # If no error, return the file_existed value we checked before deletion
        return (True, file_existed)
    except Exception as e:
        # Log but don't fail - we want to continue deleting other files
        import logging
        logging.getLogger("supabase_storage").warning(f"Failed to delete {filename} from Supabase: {e}")
        return (False, False)


def sanitize_storage_key(text: str) -> str:
    """
    Sanitize text for use in Supabase storage keys/filenames.
    
    Removes or replaces invalid characters, including Unicode characters like ellipsis.
    Only allows alphanumeric characters, hyphens, and underscores.
    
    Args:
        text: The text to sanitize
        
    Returns:
        Sanitized string safe for use in storage keys
        
    Example:
        sanitize_storage_key("My typical Sunday…") -> "my_typical_sunday"
        sanitize_storage_key("What's your favorite?") -> "whats_your_favorite"
    """
    if not text:
        return ""
    
    # Convert to lowercase
    sanitized = text.lower()
    
    # Replace spaces with underscores
    sanitized = sanitized.replace(" ", "_")
    
    # Remove all non-ASCII characters (including ellipsis '…' and other Unicode)
    # This keeps only ASCII alphanumeric, hyphens, and underscores
    sanitized = re.sub(r'[^a-z0-9_-]', '', sanitized)
    
    # Remove consecutive underscores
    sanitized = re.sub(r'_+', '_', sanitized)
    
    # Remove leading/trailing underscores and hyphens
    sanitized = sanitized.strip('_-')
    
    # Ensure we have at least one character (fallback to 'file' if empty)
    if not sanitized:
        sanitized = "file"
    
    return sanitized

# Create retry logger for upload operations
upload_retry_logger = logging.getLogger("supabase_upload_retry")

def _upload_to_supabase_storage_internal(file_content: bytes, filename: str, content_type: str = "application/octet-stream"):
    """Internal upload function that will be retried on transient errors."""
    res = supabase.storage.from_(SUPABASE_BUCKET).upload(
        path=filename,
        file=file_content,
        file_options={
            "content-type": content_type,
            "cache-control": "max-age=31536000" if content_type == "image/gif" else "max-age=3600",
            "upsert": "true",
            "x-amz-acl": "public-read",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, HEAD"
        }
    )
    if hasattr(res, "error") and res.error:
        raise Exception(f"Supabase upload failed: {res.error}")
    public_url = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(filename)
    return public_url

def _is_retryable_error(retry_state) -> bool:
    """Check if an exception is retryable (network/SSL errors)."""
    if not retry_state.outcome.failed:
        return False
    
    exception = retry_state.outcome.exception()
    if exception is None:
        return False
    
    error_str = str(exception).lower()
    # Check for SSL/network errors in the error message
    if any(keyword in error_str for keyword in ['ssl', 'bad record mac', 'connection', 'timeout', 'network', 'readerror', 'writeerror', 'broken pipe']):
        return True
    # Check exception types (including WriteError for broken pipe)
    if isinstance(exception, (httpx.ReadError, httpx.ConnectError, httpx.TimeoutException, httpx.WriteError,
                              httpcore.ReadError, httpcore.ConnectError, httpcore.TimeoutException, httpcore.WriteError)):
        return True
    return False

@retry(
    stop=stop_after_attempt(7),  # Increased from 5 to 7 attempts for better resilience
    wait=wait_exponential(multiplier=2, min=3, max=60),  # Longer waits: 3s, 6s, 12s, 24s, 48s, 60s, 60s
    retry=_is_retryable_error,
    before_sleep=before_sleep_log(upload_retry_logger, logging.WARNING),
    reraise=True
)
def _upload_with_retry(file_content: bytes, filename: str, content_type: str):
    """Upload with retry logic for transient network/SSL errors."""
    return _upload_to_supabase_storage_internal(file_content, filename, content_type)

async def upload_to_supabase_storage(file_content: bytes, filename: str, content_type: str = "application/octet-stream"):
    """
    Upload file to Supabase Storage bucket and return the public URL.
    Includes retry logic for transient SSL/network errors.
    """
    
    # Check file size limit (5MB to stay under Supabase 6MB limit with overhead)
    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB in bytes
    if len(file_content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413, 
            detail=f"File size ({len(file_content)} bytes) exceeds maximum allowed size ({MAX_FILE_SIZE} bytes). Please compress your image and try again."
        )
    
    try:
        # Use retry wrapper for the upload
        # Run in threadpool to avoid blocking the event loop during retries
        public_url = await run_in_threadpool(_upload_with_retry, file_content, filename, content_type)
        return public_url
    except (httpx.ReadError, httpx.ConnectError, httpx.TimeoutException, httpx.WriteError,
            httpcore.ReadError, httpcore.ConnectError, httpcore.TimeoutException, httpcore.WriteError) as e:
        # These are retryable network errors - should have been retried already
        logging.getLogger("supabase_storage").error(f"Supabase upload failed after retries due to network error: {type(e).__name__}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Supabase upload failed after retries due to network error: {str(e)}")
    except Exception as e:
        # Check if it's an SSL/network error that should have been retried
        error_str = str(e).lower()
        if any(keyword in error_str for keyword in ['ssl', 'bad record mac', 'connection', 'timeout', 'writeerror', 'broken pipe']):
            # This should have been caught by retry, but if it wasn't, raise with context
            logging.getLogger("supabase_storage").error(f"Supabase upload failed due to SSL/network error: {type(e).__name__}: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Supabase upload failed due to SSL/network error: {str(e)}")
        logging.getLogger("supabase_storage").error(f"Supabase upload failed: {type(e).__name__}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Supabase upload failed: {str(e)}")
