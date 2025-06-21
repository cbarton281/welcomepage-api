import os
import httpx
from fastapi import APIRouter, Depends, UploadFile, File, Form
from sqlalchemy.orm import Session
from models.welcomepage_user import WelcomepageUser
from schemas.welcomepage_user import WelcomepageUserDTO
from utils.jwt_auth import require_roles
from app import get_db
from utils.logger_factory import new_logger
import logging

logging.basicConfig(level=logging.INFO)

router = APIRouter(prefix="/api/user", tags=["user"])

# Helper to upload file to Vercel Blob Storage
async def upload_to_vercel_blob(file: UploadFile, token: str) -> str:
    url = "https://api.vercel.com/v2/blobs/upload"
    headers = {"Authorization": f"Bearer {token}"}
    files = {"file": (file.filename, await file.read(), file.content_type)}
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, files=files)
        response.raise_for_status()
        return response.json()["url"]

@router.post("/", response_model=WelcomepageUserDTO)
async def create_user(
    id: int = Form(None),
    name: str = Form(...),
    role: str = Form(...),
    location: str = Form(...),
    greeting: str = Form(...),
    selected_prompts: str = Form(...),  # JSON stringified list
    answers: str = Form(...),           # JSON stringified dict
    nickname: str = Form(None),
    handwave_emoji: str = Form(None),
    handwave_emoji_url: str = Form(None),
    profile_photo: UploadFile = File(None),
    wave_gif: UploadFile = File(None),
    pronunciation_recording: UploadFile = File(None),
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("USER", "ADMIN"))
):
    import json
    log = new_logger("create_user")
    log.info("endpoint invoked")
    vercel_token = os.getenv("VERCEL_BLOB_TOKEN")
    profile_photo_url = None
    wave_gif_url = None
    pronunciation_recording_url = None

    # Upload files if present
    if profile_photo:
        profile_photo_url = await upload_to_vercel_blob(profile_photo, vercel_token)
    if wave_gif:
        wave_gif_url = await upload_to_vercel_blob(wave_gif, vercel_token)
    if pronunciation_recording:
        pronunciation_recording_url = await upload_to_vercel_blob(pronunciation_recording, vercel_token)

    # Parse JSON fields
    selected_prompts_list = json.loads(selected_prompts)
    answers_dict = json.loads(answers)

    # UPSERT logic: update if id exists, else create
    if id is not None:
        db_user = db.query(WelcomepageUser).filter_by(id=id).first()
        if db_user:
            db_user.name = name
            db_user.role = role
            db_user.location = location
            db_user.greeting = greeting
            db_user.nickname = nickname
            db_user.handwave_emoji = handwave_emoji
            db_user.handwave_emoji_url = handwave_emoji_url
            if profile_photo_url:
                db_user.profile_photo_url = profile_photo_url
            if wave_gif_url:
                db_user.wave_gif_url = wave_gif_url
            if pronunciation_recording_url:
                db_user.pronunciation_recording_url = pronunciation_recording_url
            db_user.selected_prompts = selected_prompts_list
            db_user.answers = answers_dict
            db.commit()
            db.refresh(db_user)
            return WelcomepageUserDTO.from_model(db_user)

    # Create new user if not found
    db_user = WelcomepageUser(
        name=name,
        role=role,
        location=location,
        greeting=greeting,
        nickname=nickname,
        handwave_emoji=handwave_emoji,
        handwave_emoji_url=handwave_emoji_url,
        profile_photo_url=profile_photo_url,
        wave_gif_url=wave_gif_url,
        pronunciation_recording_url=pronunciation_recording_url,
        selected_prompts=selected_prompts_list,
        answers=answers_dict,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return WelcomepageUserDTO.from_model(db_user)

@router.get("/{user_id}", response_model=WelcomepageUserDTO)
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(WelcomepageUser).filter_by(id=user_id).first()
    if not user:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="User not found")
    return WelcomepageUserDTO.from_model(user)
