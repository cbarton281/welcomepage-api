import httpx
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models.team import Team
from schemas.team import TeamCreate, TeamRead
import os
import json
import uuid
from typing import Optional
from utils.logger_factory import new_logger

router = APIRouter()

# Correct Vercel Blob API endpoint - this is the actual REST API
VERCEL_BLOB_TOKEN = os.getenv("BLOB_READ_WRITE_TOKEN")

from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_BUCKET = "welcomepage-media"

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in environment variables.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

async def upload_to_supabase_storage(file_content: bytes, filename: str, content_type: str = "application/octet-stream"):
    """Upload file to Supabase Storage bucket 'teams' and return the public URL."""
    try:
        # Upload file to the 'teams' bucket
        res = supabase.storage.from_(SUPABASE_BUCKET).upload(
            path=filename,
            file=file_content,
            file_options={"content-type": content_type, "upsert": "true"}
        )
        if hasattr(res, "error") and res.error:
            raise Exception(f"Supabase upload failed: {res.error}")
        # Get the public URL
        public_url = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(filename)
        return public_url
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Supabase upload failed: {str(e)}")



@router.post("/teams/", response_model=TeamRead)
async def upsert_team(
    organization_name: str = Form(...),
    color_scheme: str = Form(...),
    color_scheme_data: Optional[str] = Form(None),
    company_logo: Optional[UploadFile] = File(None),
    public_id: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    logo_blob_url = None

    log = new_logger("upsert_team")
    log.info("endpoint invoked")    
    # Handle logo upload
    # Upsert team record (update if exists, else create)
    # Use public_id for lookup if provided, else create new team
    if public_id:
        team = db.query(Team).filter_by(public_id=public_id).first()
    else:
        team = None

    generated_uuid = None
    if not team:
        import uuid
        generated_uuid = str(uuid.uuid4())

    if company_logo and company_logo.filename:
        try:
            log.info("logo uploaded")
            # Read the file content
            logo_content = await company_logo.read()
            # Use the correct public_id for filename, omit file extension
            logo_public_id = team.public_id if team else generated_uuid
            logo_filename = f"{logo_public_id}-company-logo"
            log.info(f"logo filename: {logo_filename}")
            # Upload to Supabase Storage
            logo_blob_url = await upload_to_supabase_storage(
                file_content=logo_content,
                filename=logo_filename,
                content_type=company_logo.content_type or "image/jpeg"
            )
            log.info(f"Logo uploaded successfully: {logo_blob_url}")
            
        except Exception as e:
            log.error(f"Error uploading logo: {str(e)}")
            # Don't fail the entire request if logo upload fails
            log.info("Continuing without logo upload...")
    
    # Parse color scheme data
    color_scheme_obj = None
    if color_scheme_data:
        try:
            color_scheme_obj = json.loads(color_scheme_data)
            log.info(f"color scheme data: {color_scheme_obj}")
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON in color_scheme_data")
    
    if team:
        log.info("Team exists, updating...")
        team.color_scheme = color_scheme
        team.company_logo_url = logo_blob_url
        team.color_scheme_data = color_scheme_obj
    else:
        log.info("Team does not exist, creating new team...")
        team = Team(
            public_id=generated_uuid,
            organization_name=organization_name,
            color_scheme=color_scheme,
            company_logo_url=logo_blob_url,
            color_scheme_data=color_scheme_obj
        )
        db.add(team)
    db.commit()
    db.refresh(team)
    return team