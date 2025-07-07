import httpx
import os
import json
import uuid
import logging
from typing import Optional

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log

from database import get_db
from models.team import Team
from schemas.team import TeamCreate, TeamRead
from utils.logger_factory import new_logger
from utils.jwt_auth import require_roles
from utils.supabase_storage import upload_to_supabase_storage

router = APIRouter()

team_retry_logger = new_logger("fetch_team_by_public_id_retry")

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(OperationalError),
    before_sleep=before_sleep_log(team_retry_logger, logging.WARNING)
)
def fetch_team_by_public_id(db: Session, public_id: str):
    try:
        return db.query(Team).filter_by(public_id=public_id).first()
    except OperationalError:
        db.rollback()
        raise

@router.get("/teams/{public_id}", response_model=TeamRead)
async def get_team(public_id: str, db: Session = Depends(get_db), current_user=Depends(require_roles("USER", "ADMIN"))):
    log = new_logger("get_team")
    log.info(f"Fetching team with public_id: {public_id}")
    team = fetch_team_by_public_id(db, public_id)
    if not team:
        log.warning(f"Team not found: {public_id}")
        raise HTTPException(status_code=404, detail="Team not found")
    else:
        log.info(f"Team found [{team.to_dict()}]")
    return team

@router.post("/teams/", response_model=TeamRead)
async def upsert_team(
    organization_name: str = Form(...),
    color_scheme: str = Form(...),
    color_scheme_data: Optional[str] = Form(None),
    company_logo: Optional[UploadFile] = File(None),
    public_id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("ADMIN", "PRE_SIGNUP"))
):
    logo_blob_url = None

    log = new_logger("upsert_team")
    log.info(f"endpoint invoked [{organization_name}] [{public_id}] ")    
    # Upsert team record (update if exists, else create)
    team = None
    team_lookup_id = None
    if public_id:
        team = fetch_team_by_public_id(db, public_id)
        if not team:
            team_lookup_id = public_id
    if not team:
        generated_uuid = str(uuid.uuid4())

    effective_public_id = team.public_id if team else (team_lookup_id if team_lookup_id else generated_uuid)

    # --- PRE_SIGNUP logic enforcement ---
    user_role = current_user.get('role')
    if user_role == 'PRE_SIGNUP':
        if team and not team.is_draft:
            log.warning(f"PRE_SIGNUP user attempted to update finalized team [{effective_public_id}]")
            raise HTTPException(status_code=403, detail="Drafts can only be updated until finalized.")
        # Otherwise, allow create or update (if is_draft)

    if company_logo and company_logo.filename:
        try:
            log.info("logo uploaded")
            logo_content = await company_logo.read()
            logo_filename = f"{effective_public_id}-company-logo"
            log.info(f"logo filename: {logo_filename}")
            logo_blob_url = await upload_to_supabase_storage(
                file_content=logo_content,
                filename=logo_filename,
                content_type=company_logo.content_type or "image/jpeg"
            )
            log.info(f"Logo uploaded successfully: {logo_blob_url}")
        except Exception as e:
            log.error(f"Error uploading logo: {str(e)}")
            log.info("Continuing without logo upload...")
    
    # Parse color scheme data
    color_scheme_obj = None
    if color_scheme_data:
        try:
            color_scheme_obj = json.loads(color_scheme_data)
            log.info(f"color scheme data: {color_scheme_obj}")
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON in color_scheme_data")
    try:
        if team:
            log.info("Team exists, updating...")
            team.organization_name = organization_name
            team.color_scheme = color_scheme
            team.company_logo_url = logo_blob_url
            team.color_scheme_data = color_scheme_obj
        else:
            log.info("Creating new team...")
            team = Team(
                public_id=effective_public_id,
                organization_name=organization_name,
                color_scheme=color_scheme,
                color_scheme_data=color_scheme_obj,
                company_logo_url=logo_blob_url,
            )
            db.add(team)
        db.commit()
        db.refresh(team)
        log.info(f"Upserted team: {team.to_dict()}")
        return team
    except Exception as e:
        db.rollback()
        log.error(f"DB error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to upsert team")