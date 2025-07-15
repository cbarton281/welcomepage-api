
import json
import uuid
import logging
from fastapi import APIRouter, Depends, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log
from models.welcomepage_user import WelcomepageUser
from schemas.welcomepage_user import WelcomepageUserDTO
from database import get_db
from utils.logger_factory import new_logger
from utils.jwt_auth import require_roles
from fastapi import HTTPException
from utils.supabase_storage import upload_to_supabase_storage

router = APIRouter()

user_retry_logger = new_logger("fetch_user_by_id_retry")

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(OperationalError),
    before_sleep=before_sleep_log(user_retry_logger, logging.WARNING)
)
def fetch_user_by_id(db: Session, user_id: int):
    try:
        return db.query(WelcomepageUser).filter_by(id=user_id).first()
    except OperationalError:
        db.rollback()
        raise

@router.post("/users/", response_model=WelcomepageUserDTO)
async def upsert_user(
    id: int = Form(None),
    public_id: str = Form(None),  # <-- Added public_id as a Form parameter
    name: str = Form(...),
    role: str = Form(None),
    location: str = Form(None),
    greeting: str = Form(None),
    selected_prompts: str = Form(None),  # JSON stringified list
    answers: str = Form(None),           # JSON stringified dict
    nickname: str = Form(None),
    handwave_emoji: str = Form(None),
    handwave_emoji_url: str = Form(None),
    team_id: int = Form(...),  # REQUIRED
    profile_photo: UploadFile = File(None),
    wave_gif: UploadFile = File(None),
    pronunciation_recording: UploadFile = File(None),
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("USER", "ADMIN", "PRE_SIGNUP"))
):
    
    log = new_logger("upsert_user")

    try:
        log.info("endpoint invoked")
   
        # Parse JSON fields
        selected_prompts_list = json.loads(selected_prompts)
        answers_dict = json.loads(answers)

        # Enforce that team_id is present
        if team_id is None:
            raise HTTPException(status_code=422, detail="team_id is required and must be an integer")

        # UPSERT logic: update if id exists, else create
        db_user = None
        user_identifier = None
        user_lookup_id = None
        if id is not None:
            db_user = db.query(WelcomepageUser).filter_by(id=id).first()
        # Support client-supplied public_id for upsert
        if db_user is None and public_id:
            db_user = db.query(WelcomepageUser).filter_by(public_id=public_id).first()
            if not db_user:
                user_lookup_id = public_id
        if db_user:
            user_identifier = str(db_user.id)
            # Update user fields
            db_user.name = name
            db_user.role = role
            db_user.location = location
            db_user.greeting = greeting
            db_user.nickname = nickname
            db_user.handwave_emoji = handwave_emoji
            db_user.handwave_emoji_url = handwave_emoji_url
            db_user.selected_prompts = selected_prompts_list
            db_user.answers = answers_dict
            db_user.team_id = team_id
            # Always commit and refresh after update
            try:
                db.commit()
                db.refresh(db_user)
            except Exception as e:
                db.rollback()
                log.exception("Database commit/refresh failed.")
                raise HTTPException(status_code=500, detail="Database error. Please try again later.")
        else:
            # Create new user
            effective_public_id = user_lookup_id if user_lookup_id else str(uuid.uuid4())
            db_user = WelcomepageUser(
                public_id=effective_public_id,
                name=name,
                role=role,
                location=location,
                greeting=greeting,
                nickname=nickname,
                handwave_emoji=handwave_emoji,
                handwave_emoji_url=handwave_emoji_url,
                selected_prompts=selected_prompts_list,
                answers=answers_dict,
                team_id=team_id,
            )
            db.add(db_user)
            try:
                db.commit()
                db.refresh(db_user)
            except Exception as e:
                db.rollback()
                log.exception("Database commit/refresh failed.")
                raise HTTPException(status_code=500, detail="Database error. Please try again later.")
            user_identifier = str(db_user.id) if db_user.id else temp_uuid
        # Handle uploads for both update and create
        updated = False
        if profile_photo:
            photo_filename = f"{db_user.public_id}-profile-photo"
            content = await profile_photo.read()
            db_user.profile_photo_url = await upload_to_supabase_storage(
                file_content=content,
                filename=photo_filename,
                content_type=profile_photo.content_type or "image/jpeg"
            )
            updated = True
        if wave_gif:
            gif_filename = f"{db_user.public_id}-wave-gif"
            content = await wave_gif.read()
            db_user.wave_gif_url = await upload_to_supabase_storage(
                file_content=content,
                filename=gif_filename,
                content_type=wave_gif.content_type or "image/gif"
            )
            updated = True
        if pronunciation_recording:
            audio_filename = f"{db_user.public_id}-pronunciation-audio"
            content = await pronunciation_recording.read()
            db_user.pronunciation_recording_url = await upload_to_supabase_storage(
                file_content=content,
                filename=audio_filename,
                content_type=pronunciation_recording.content_type or "audio/mpeg"
            )
            updated = True
        if updated:
            try:
                db.commit()
                db.refresh(db_user)
            except Exception as e:
                db.rollback()
                log.exception("Database commit/refresh failed.")
                raise HTTPException(status_code=500, detail="Database error. Please try again later.")
        return WelcomepageUserDTO.from_model(db_user)
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        log.exception("Unhandled exception in upsert_user")
        raise HTTPException(status_code=500, detail="Internal server error")




@router.get("/users/{public_id}", response_model=WelcomepageUserDTO)
def get_user(public_id: str, db: Session = Depends(get_db), current_user=Depends(require_roles("USER", "ADMIN", "PRE_SIGNUP"))):
    log = new_logger("get_user")
    log.info(f"Fetching user with public_id: {public_id}")
    user = db.query(WelcomepageUser).filter_by(public_id=public_id).first()
    if not user:
        log.info(f"User not found: {public_id}")
        raise HTTPException(status_code=404, detail="User not found")
    else:
        log.info(f"User found [{user.to_dict()}]")
    return WelcomepageUserDTO.from_model(user)
