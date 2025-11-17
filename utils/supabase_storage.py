import os
import re
from fastapi import HTTPException
from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_BUCKET = "welcomepage-media"

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in environment variables.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


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

async def upload_to_supabase_storage(file_content: bytes, filename: str, content_type: str = "application/octet-stream"):
    """Upload file to Supabase Storage bucket and return the public URL."""
    
    # Check file size limit (5MB to stay under Supabase 6MB limit with overhead)
    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB in bytes
    if len(file_content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413, 
            detail=f"File size ({len(file_content)} bytes) exceeds maximum allowed size ({MAX_FILE_SIZE} bytes). Please compress your image and try again."
        )
    
    try:
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Supabase upload failed: {str(e)}")
