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

async def upload_to_vercel_blob(file_content: bytes, filename: str, content_type: str = "application/octet-stream"):
    """Upload file to Vercel Blob using the correct API format"""
    if not VERCEL_BLOB_TOKEN:
        raise HTTPException(status_code=500, detail="BLOB_READ_WRITE_TOKEN not set")
    
    # Extract store ID from token (first part before the underscore)
    try:
        store_id = VERCEL_BLOB_TOKEN.split('_')[0]
    except:
        raise HTTPException(status_code=500, detail="Invalid BLOB_READ_WRITE_TOKEN format")
    
    # Construct the correct API URL with store ID
    api_url = f"https://{store_id}.public.blob.vercel-storage.com"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # First, we need to get an upload URL
        headers = {
            "Authorization": f"Bearer {VERCEL_BLOB_TOKEN}",
            "Content-Type": "application/json"
        }
        
        # Request upload URL
        upload_request = {
            "pathname": f"teams/{filename}",
            "access": "public",
            "contentType": content_type
        }
        
        # Try the PUT method with query parameters instead
        params = {
            "pathname": f"teams/{filename}",
            "access": "public"
        }
        
        headers_upload = {
            "Authorization": f"Bearer {VERCEL_BLOB_TOKEN}",
            "Content-Type": content_type
        }
        
        # Use PUT method with the file content directly
        response = await client.put(
            f"{api_url}/{filename}",
            content=file_content,
            headers=headers_upload,
            params=params
        )
        
        print(f"Vercel Blob response: {response.status_code}")
        print(f"Response body: {response.text}")
        
        if response.status_code in [200, 201]:
            # Construct the response manually if needed
            blob_url = f"{api_url}/teams/{filename}"
            return {
                "url": blob_url,
                "pathname": f"teams/{filename}",
                "contentType": content_type,
                "size": len(file_content)
            }
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Vercel Blob upload failed: {response.status_code} - {response.text}"
            )

@router.post("/teams/", response_model=TeamRead)
async def create_team(
    organization_name: str = Form(...),
    color_scheme: str = Form(...),
    color_scheme_data: Optional[str] = Form(None),
    company_logo: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    logo_blob_url = None

    log = new_logger("create_team")
    log.info("endpoint invoked")    
    # Handle logo upload
    if company_logo and company_logo.filename:
        try:
            log.info("logo uploaded")
            # Read the file content
            logo_content = await company_logo.read()
            
            # Create a safe filename
            file_ext = os.path.splitext(company_logo.filename)[1]
            safe_org_name = "".join(c for c in organization_name if c.isalnum() or c in ('-', '_')).strip()
            logo_filename = f"{safe_org_name}_logo_{uuid.uuid4().hex[:8]}{file_ext}"
            log.info(f"logo filename: {logo_filename}")
            # Upload to Vercel Blob
            blob_response = await upload_to_vercel_blob(
                file_content=logo_content,
                filename=logo_filename,
                content_type=company_logo.content_type or "image/jpeg"
            )
            
            logo_blob_url = blob_response.get("url")
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
    
    # Create team record
    team = Team(
        organization_name=organization_name,
        color_scheme=color_scheme,
        company_logo=logo_blob_url,
        color_scheme_data=color_scheme_obj
    )
    
    db.add(team)
    db.commit()
    db.refresh(team)
    
    return team