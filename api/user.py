
import json
import uuid
import logging
from fastapi import APIRouter, Depends, UploadFile, File, Form, Request
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
from sqlalchemy import text
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log
from models.welcomepage_user import WelcomepageUser
from schemas.welcomepage_user import WelcomepageUserDTO
from database import get_db
from utils.logger_factory import new_logger
from utils.jwt_auth import require_roles
from fastapi import HTTPException
from utils.supabase_storage import upload_to_supabase_storage
from datetime import datetime, timezone

router = APIRouter()

from pydantic import BaseModel
from fastapi import Body

class UserAuthUpdateRequest(BaseModel):
    public_id: str
    auth_email: str
    auth_role: str

user_retry_logger = new_logger("fetch_user_by_id_retry")

@router.post("/users/update_auth_fields", response_model=WelcomepageUserDTO)
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(OperationalError),
    before_sleep=before_sleep_log(user_retry_logger, logging.WARNING)
)
def update_auth_fields(
    payload: UserAuthUpdateRequest = Body(...),
    db: Session = Depends(get_db),
):
    log = new_logger("update_auth_fields")
    log.info(f"Updating auth fields for user [{payload.public_id}]")
    user = db.query(WelcomepageUser).filter_by(public_id=payload.public_id).first()
    if not user:
        log.info(f"User not found for public_id [{payload.public_id}]")
        raise HTTPException(status_code=404, detail="User not found")
    log.info(f"User found [{user.public_id}, {user.role}, {user.name}, {user.auth_email}, {user.auth_role}]")
    user.auth_email = payload.auth_email
    user.auth_role = payload.auth_role
    try:
        db.commit()
        db.refresh(user)
    except OperationalError as e:
        db.rollback()
        log.exception("OperationalError in verify_code_with_retry, will retry.")
        raise  # trigger the retry
    except Exception as e:
        db.rollback()
        log.exception("Database commit/refresh failed in update_auth_fields.")
        raise HTTPException(status_code=500, detail="Database error. Please try again later.")
    log.info(f"Updated user [{user.public_id}] with auth_email [{user.auth_email}] and auth_role [{user.auth_role}]")
    return user

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

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log
from sqlalchemy.exc import OperationalError
import logging

upsert_retry_logger = logging.getLogger("upsert_retry")

from fastapi.concurrency import run_in_threadpool

@router.post("/users/", response_model=WelcomepageUserDTO)
async def upsert_user(
    request: Request,
    id: int = Form(None),
    public_id: str = Form(None),
    name: str = Form(...),
    role: str = Form(...),
    auth_role: str = Form(None),
    auth_email: str = Form(None),
    location: str = Form(None),
    greeting: str = Form(None),
    nickname: str = Form(None),
    hi_yall_text: str = Form(None),
    handwave_emoji: str = Form(None),
    handwave_emoji_url: str = Form(None),
    selected_prompts: str = Form(None),
    answers: str = Form(None),
    team_id: int = Form(None),
    profile_photo: UploadFile = File(None),
    wave_gif: UploadFile = File(None),
    pronunciation_recording: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    log = new_logger("upsert_user")
    
    # Step 1: Process all file uploads first and get URLs
    form_data = await request.form()
    
    # Handle profile photo upload
    profile_photo_url = None
    if profile_photo:
        photo_filename = f"{public_id or str(uuid.uuid4())}-profile-photo"
        content = await profile_photo.read()
        profile_photo_url = await upload_to_supabase_storage(
            file_content=content,
            filename=photo_filename,
            content_type=profile_photo.content_type or "image/jpeg"
        )
        log.info(f"Uploaded profile photo: {profile_photo_url}")
    
    # Handle wave gif upload
    wave_gif_url = None
    if wave_gif:
        gif_filename = f"{public_id or str(uuid.uuid4())}-wave-gif"
        content = await wave_gif.read()
        wave_gif_url = await upload_to_supabase_storage(
            file_content=content,
            filename=gif_filename,
            content_type=wave_gif.content_type or "image/gif"
        )
        log.info(f"Uploaded wave gif: {wave_gif_url}")
    
    # Handle pronunciation recording upload
    pronunciation_recording_url = None
    if pronunciation_recording:
        audio_filename = f"{public_id or str(uuid.uuid4())}-pronunciation-audio"
        content = await pronunciation_recording.read()
        pronunciation_recording_url = await upload_to_supabase_storage(
            file_content=content,
            filename=audio_filename,
            content_type=pronunciation_recording.content_type or "audio/mpeg"
        )
        log.info(f"Uploaded pronunciation recording: {pronunciation_recording_url}")
    
    # Step 2: Process prompt images and build complete answers structure
    # Parse the answers JSON to get the base structure
    try:
        answers_dict = json.loads(answers or "{}")
    except Exception as e:
        log.warning(f"Invalid answers JSON: {answers!r}. Using empty dict. Error: {e}")
        answers_dict = {}
    
    # Process dynamic prompt image uploads
    for field_name, file_data in form_data.items():
        if field_name.startswith("answer_image_") and hasattr(file_data, 'filename') and file_data.filename:
            # Extract prompt text from field name
            prompt_text = field_name.replace("answer_image_", "")
            log.info(f"Processing image upload for prompt: '{prompt_text}'")
            
            # Create safe filename
            safe_prompt_label = prompt_text.replace("?", "").replace("'", "").replace(" ", "_").replace(".", "").replace(",", "").replace("/", "_").replace("\\", "_").replace(":", "_").lower()
            image_filename = f"{public_id or str(uuid.uuid4())}-prompt-{safe_prompt_label}"
            
            # Upload image to Supabase
            content = await file_data.read()
            image_url = await upload_to_supabase_storage(
                file_content=content,
                filename=image_filename,
                content_type=file_data.content_type or "image/jpeg"
            )
            
            # Ensure prompt exists in answers_dict
            if prompt_text not in answers_dict:
                answers_dict[prompt_text] = {"text": "", "image": None, "specialData": None}
            elif not isinstance(answers_dict[prompt_text], dict):
                answers_dict[prompt_text] = {"text": "", "image": None, "specialData": None}
            
            # Add image metadata to answers
            answers_dict[prompt_text]["image"] = {
                "filename": file_data.filename,
                "contentType": file_data.content_type or "image/jpeg",
                "size": len(content),
                "url": image_url
            }
            
            log.info(f"Uploaded prompt image for '{prompt_text}': {image_url}")
    
    # Step 3: Save complete user record with all URLs in one database operation
    db_user, user_identifier, temp_uuid = await run_in_threadpool(
        upsert_user_db_logic, id, public_id, name, role, auth_role, auth_email, location, greeting, nickname, hi_yall_text, handwave_emoji, handwave_emoji_url, selected_prompts, json.dumps(answers_dict), team_id, db, log, profile_photo_url, wave_gif_url, pronunciation_recording_url
    )

    return WelcomepageUserDTO.from_model(db_user)

@retry(
    stop=stop_after_attempt(5),  # Increased attempts for connection issues
    wait=wait_exponential(multiplier=1, min=2, max=15),  # Longer max wait for connection recovery
    retry=retry_if_exception_type((OperationalError, Exception)),  # Catch broader exceptions
    before_sleep=before_sleep_log(upsert_retry_logger, logging.WARNING)
)
def upsert_user_db_logic(
    id, public_id, name, role, auth_role, auth_email, location, greeting, nickname, hi_yall_text, handwave_emoji, handwave_emoji_url, selected_prompts, answers, team_id, db, log, profile_photo_url=None, wave_gif_url=None, pronunciation_recording_url=None
):
    # All arguments are plain values, no FastAPI Form/File/Depends here
    # All business logic remains unchanged
    try:
        log.info("endpoint invoked")
        
        # Test database connection and recover if stale
        try:
            db.execute(text("SELECT 1"))
        except OperationalError as e:
            log.warning(f"Database connection appears stale, attempting to recover: {e}")
            db.rollback()
            # Force connection refresh
            db.close()
            # The next query will create a new connection
        

   
        # Parse JSON fields with guards
        try:
            selected_prompts_list = json.loads(selected_prompts or "[]")
        except Exception as e:
            log.warning(f"Invalid selected_prompts: {selected_prompts!r}. Using empty list. Error: {e}")
            selected_prompts_list = []
        try:
            answers_dict = json.loads(answers or "{}")
            # Sanitize answers to ensure null image values stay null
            for prompt, answer in answers_dict.items():
                if isinstance(answer, dict) and 'image' in answer:
                    # Convert empty dict {} to None for image field
                    if answer['image'] == {}:
                        answer['image'] = None
        except Exception as e:
            log.warning(f"Invalid answers: {answers!r}. Using empty dict. Error: {e}")
            answers_dict = {}
        
        # Ensure answers_dict includes all selected prompts with proper structure
        for prompt in selected_prompts_list:
            if prompt not in answers_dict:
                answers_dict[prompt] = {"text": "", "image": None, "specialData": None}

        # Enforce that team_id is present
        if team_id is None:
            raise HTTPException(status_code=422, detail="team_id is required and must be an integer")

        # UPSERT logic: update if id exists, else create
        db_user = None
        user_identifier = None
        user_lookup_id = None
        
        # Wrap database queries with additional error handling
        try:
            if id is not None:
                db_user = db.query(WelcomepageUser).filter_by(id=id).first()
            # Support client-supplied public_id for upsert
            if db_user is None and public_id:
                db_user = db.query(WelcomepageUser).filter_by(public_id=public_id).first()
                if not db_user:
                    user_lookup_id = public_id
        except OperationalError as e:
            log.warning(f"Database query failed, will be retried by tenacity: {e}")
            raise  # Let tenacity handle the retry
        if db_user:
            user_identifier = str(db_user.id)
            # Update user fields
            db_user.name = name
            db_user.role = role
            db_user.auth_role = auth_role if auth_role is not None else db_user.auth_role
            db_user.auth_email = auth_email if auth_email is not None else db_user.auth_email
            db_user.location = location
            db_user.greeting = greeting
            db_user.nickname = nickname
            db_user.hi_yall_text = hi_yall_text
            db_user.handwave_emoji = handwave_emoji
            db_user.handwave_emoji_url = handwave_emoji_url
            db_user.selected_prompts = selected_prompts_list
            db_user.answers = answers_dict
            db_user.team_id = team_id
            
            # Update file URLs if provided
            if profile_photo_url:
                db_user.profile_photo_url = profile_photo_url
            if wave_gif_url:
                db_user.wave_gif_url = wave_gif_url
            if pronunciation_recording_url:
                db_user.pronunciation_recording_url = pronunciation_recording_url
            # Always commit and refresh after update
            try:
                db.commit()
                db.refresh(db_user)
            except OperationalError as e:
                db.rollback()
                log.exception("OperationalError in verify_code_with_retry, will retry.")
                raise  # trigger the retry
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
                auth_role=auth_role,
                auth_email=auth_email,
                location=location,
                greeting=greeting,
                nickname=nickname,
                hi_yall_text=hi_yall_text,
                handwave_emoji=handwave_emoji,
                handwave_emoji_url=handwave_emoji_url,
                selected_prompts=selected_prompts_list,
                answers=answers_dict,
                team_id=team_id,
                is_draft=True,
                profile_photo_url=profile_photo_url,
                wave_gif_url=wave_gif_url,
                pronunciation_recording_url=pronunciation_recording_url,
                team_settings=None,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(db_user)
            try:
                db.commit()
                db.refresh(db_user)
            except OperationalError as e:
                db.rollback()
                log.exception("OperationalError in verify_code_with_retry, will retry.")
                raise  # trigger the retry
            except Exception as e:
                db.rollback()
                log.exception("Database commit/refresh failed.")
                raise HTTPException(status_code=500, detail="Database error. Please try again later.")
            user_identifier = str(db_user.id) if db_user.id else db_user.public_id
        # All file upload and await logic must be in the async route handler, not here.
        # Only DB upsert logic remains here.
        return db_user, user_identifier, db_user.public_id
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
    
    # Sanitize user data before Pydantic validation
    user_dict = user.to_dict()
    if user_dict.get('answers'):
        for prompt, answer in user_dict['answers'].items():
            if isinstance(answer, dict) and 'image' in answer:
                # Convert empty dict {} to None for image field
                if answer['image'] == {}:
                    answer['image'] = None
    
    return WelcomepageUserDTO(**user_dict)
