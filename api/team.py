import httpx
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models.team import Team
from schemas.team import TeamCreate, TeamRead
import shutil
import os

router = APIRouter()

UPLOAD_DIR = "uploads/logos"
os.makedirs(UPLOAD_DIR, exist_ok=True)

VERCEL_BLOB_API_URL = "https://api.vercel.com/v2/blobs/upload"
VERCEL_BLOB_TOKEN = os.getenv("VERCEL_BLOB_TOKEN")  # Store your Vercel token in env

@router.post("/teams/", response_model=TeamRead)
async def create_team(
    organization_name: str = Form(...),
    color_scheme: str = Form(...),
    color_scheme_data: str = Form(None),
    company_logo: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    logo_path = None
    if company_logo:
        file_ext = os.path.splitext(company_logo.filename)[1]
        logo_filename = f"{organization_name}_{company_logo.filename}"
        logo_path = os.path.join(UPLOAD_DIR, logo_filename)
        with open(logo_path, "wb") as buffer:
            shutil.copyfileobj(company_logo.file, buffer)
        logo_path = f"/{logo_path}"  # Adjust if serving statically

    # --- Upload company name as blob to Vercel ---
    blob_url = None
    if not VERCEL_BLOB_TOKEN:
        raise HTTPException(status_code=500, detail="VERCEL_BLOB_TOKEN not set in environment")
    async with httpx.AsyncClient() as client:
        files = {
            "file": ("company_name.txt", organization_name, "text/plain"),
        }
        headers = {"Authorization": f"Bearer {VERCEL_BLOB_TOKEN}"}
        response = await client.post(VERCEL_BLOB_API_URL, files=files, headers=headers)
        print("Vercel response:", response.status_code, response.text)
        if response.status_code == 200:
            blob_url = response.json().get("url")
        else:
            raise HTTPException(status_code=500, detail="Failed to upload company name to Vercel Blob")

    import json
    color_scheme_obj = json.loads(color_scheme_data) if color_scheme_data else None
    team = Team(
        organization_name=organization_name,
        color_scheme=color_scheme,
        company_logo=logo_path,
        company_name_blob_url=blob_url,
        color_scheme_data=color_scheme_obj
    )
    db.add(team)
    db.commit()
    db.refresh(team)
    return team
