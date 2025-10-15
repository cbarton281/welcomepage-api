import json
import logging
from fastapi import APIRouter, Depends, UploadFile, File, Form, Request
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, IntegrityError, DataError, DatabaseError
from sqlalchemy import text
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log
from models.welcomepage_user import WelcomepageUser
from models.team import Team
from schemas.welcomepage_user import WelcomepageUserDTO
from database import get_db
from utils.logger_factory import new_logger
from utils.jwt_auth import require_roles
from fastapi import HTTPException
from utils.supabase_storage import upload_to_supabase_storage
from datetime import datetime, timezone
from schemas.peer_data import PeerDataResponse, PeerAnswer
from utils.short_id import generate_short_id_with_collision_check, generate_file_id

router = APIRouter()

from pydantic import BaseModel
from fastapi import Body

class UserAuthUpdateRequest(BaseModel):
    public_id: str
    auth_email: str
    auth_role: str

class GoogleAuthRequest(BaseModel):
    email: str
    name: str
    google_id: str
    public_id: str = None  # Optional - from anonymous user cookies
    team_public_id: str = None  # Optional - from anonymous user cookies

class InviteBannerDismissRequest(BaseModel):
    dismissed: bool

# Minimal preview response
class UserPreviewResponse(BaseModel):
    public_id: str
    display_name: str
    team_public_id: str

class EnsureInTeamRequest(BaseModel):
    target_user_public_id: str

class EnsureInTeamResponse(BaseModel):
    success: bool
    team_public_id: str
    user_public_id: str

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
    except OperationalError:
        # These exceptions are handled by the @retry decorator - let them bubble up
        db.rollback()
        raise
    except Exception as e:
        # Only catch non-retryable exceptions here
        db.rollback()
        log.exception("Non-retryable database error in update_auth_fields.")
        raise HTTPException(status_code=500, detail="Database error. Please try again later.")

@router.patch("/users/me/invite_banner", response_model=WelcomepageUserDTO)
def update_invite_banner(
    payload: InviteBannerDismissRequest = Body(...),
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("USER", "ADMIN"))
):
    """
    Update the current authenticated user's invite banner dismissed flag.
    Only authenticated users (USER/ADMIN) are allowed to persist this change.
    """
    log = new_logger("update_invite_banner")
    user_public_id = current_user.get('user_id')
    log.info(f"Updating invite_banner_dismissed for user [{user_public_id}] to [{payload.dismissed}]")

    try:
        user = db.query(WelcomepageUser).filter_by(public_id=user_public_id).first()
        if not user:
            log.info(f"User not found for public_id [{user_public_id}]")
            raise HTTPException(status_code=404, detail="User not found")

        user.invite_banner_dismissed = payload.dismissed
        user.updated_at = datetime.now(timezone.utc)

        try:
            db.commit()
            db.refresh(user)
        except OperationalError:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            log.exception("Non-retryable database error in update_invite_banner.")
            raise HTTPException(status_code=500, detail="Database error. Please try again later.")

        return WelcomepageUserDTO.model_validate(user)
    except OperationalError:
        # These exceptions are handled by the retry decorator if applied; here we just propagate
        raise
    log.info(f"Updated user [{user.public_id}] with auth_email [{user.auth_email}] and auth_role [{user.auth_role}]")
    return WelcomepageUserDTO.model_validate(user)

@router.post("/users/google_auth")
def google_auth(
    payload: GoogleAuthRequest = Body(...),
    db: Session = Depends(get_db),
):
    """
    Enhanced Google authentication with two-step lookup:
    1. Try to find existing user by email (returning user)
    2. If not found, try by cookie public_id (anonymous user converting)
    3. If neither exists, create new user and potentially team
    4. Update auth fields and return user data for session
    """
    log = new_logger("google_auth")
    log.info(f"Google auth attempt for email [{payload.email}], name [{payload.name}]")
    log.info(f"Cookie data - public_id [{payload.public_id}], team_public_id [{payload.team_public_id}]")
    
    try:
        # Domain security helpers
        def _normalize_email_domain(email: str) -> str:
            parts = (email or "").split("@")
            return parts[-1].strip().lower() if len(parts) == 2 else ""

        def _normalize_domain(d: str) -> str:
            d = (d or "").strip().lower()
            if d.startswith("@"): d = d[1:]
            return d

        def _domain_allowed(domain: str, allowed: list[str]) -> bool:
            if not allowed:
                return True
            for rule in allowed:
                rule = _normalize_domain(rule)
                if not rule:
                    continue
                if rule.startswith("*."):
                    base = rule[2:]
                    if domain == base or domain.endswith("." + base):
                        return True
                else:
                    if domain == rule:
                        return True
            return False

        # Resolve team context for enforcement (no grandfathering, enforce all roles)
        team_for_policy = None
        # If existing user by email, use that user's team
        existing_user = db.query(WelcomepageUser).filter_by(auth_email=payload.email).first()
        if existing_user and existing_user.team_id:
            team_for_policy = db.query(Team).filter_by(id=existing_user.team_id).first()
        # Else try cookie public_id
        if team_for_policy is None and payload.public_id:
            cookie_user = db.query(WelcomepageUser).filter_by(public_id=payload.public_id).first()
            if cookie_user and cookie_user.team_id:
                team_for_policy = db.query(Team).filter_by(id=cookie_user.team_id).first()
        # Else try team_public_id param
        if team_for_policy is None and payload.team_public_id:
            team_for_policy = db.query(Team).filter_by(public_id=payload.team_public_id).first()

        # If we have a team context and policy is enabled, enforce it. If no team context,
        # this is a new user + new team scenario; domain policy is team-specific and doesn't apply yet.
        if team_for_policy is not None:
            settings = (team_for_policy.security_settings or {})
            if bool(settings.get('domain_check_enabled')):
                domain = _normalize_email_domain(payload.email)
                allowed_list = settings.get('allowed_domains') or []
                if not _domain_allowed(domain, allowed_list):
                    log.warning(f"Blocked Google auth due to domain policy. domain={domain}, team={team_for_policy.public_id}")
                    raise HTTPException(status_code=403, detail="Authentication is not allowed for this email.")

        # Domain enforcement passed; proceed with normal flow
        # Step 1: Try to find user by email (existing authenticated user)
        existing_user = db.query(WelcomepageUser).filter_by(auth_email=payload.email).first()
        if existing_user:
            log.info(f"Found existing user by email [{existing_user.public_id}] - returning user")
            log.info(f"Google authentication successful")
            
            return {
                "success": True,
                "public_id": existing_user.public_id,
                "auth_role": existing_user.auth_role,
                "team_public_id": existing_user.team.public_id if existing_user.team else None,
                "message": "Existing user authenticated"
            }
        
        # Step 2: Try to find user by cookie public_id (anonymous user converting)
        if payload.public_id:
            anonymous_user = db.query(WelcomepageUser).filter_by(public_id=payload.public_id).first()
            if anonymous_user:
                log.info(f"Found anonymous user by public_id [{anonymous_user.public_id}] - converting to authenticated")
                # Update the anonymous user with Google auth info
                anonymous_user.auth_email = payload.email
                anonymous_user.auth_role = "ADMIN"
                log.info(f"Converting anonymous user to Google auth")
                # Update name if it was placeholder or empty
                if not anonymous_user.name or anonymous_user.name.startswith("User"):
                    anonymous_user.name = payload.name
                
                db.commit()
                db.refresh(anonymous_user)
                
                return {
                    "success": True,
                    "public_id": anonymous_user.public_id,
                    "auth_role": anonymous_user.auth_role,
                    "team_public_id": anonymous_user.team.public_id if anonymous_user.team else None,
                    "message": "Anonymous user converted to authenticated"
                }
        
        # Step 3: Create new user and team (no team context to enforce yet)
        log.info("No existing user found - creating new user and team")
        
        # Create new team first
        team_public_id = generate_short_id_with_collision_check(db, Team, "team")
        new_team = Team(
            public_id=team_public_id,
            organization_name=f"{payload.name}'s Team",  # Default team name
            color_scheme="corporate-blue",
        )
        db.add(new_team)
        db.flush()  # Get the team ID
        
        # Create new user
        user_public_id = generate_short_id_with_collision_check(db, WelcomepageUser, "user")
        new_user = WelcomepageUser(
            public_id=user_public_id,
            name=payload.name,
            role="",
            auth_role="ADMIN",
            auth_email=payload.email,
            team_id=new_team.id,
            created_at=datetime.now(timezone.utc)
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        log.info(f"Created new user [{new_user.public_id}] and team [{new_team.public_id}]")
        
        return {
            "success": True,
            "public_id": new_user.public_id,
            "auth_role": new_user.auth_role,
            "team_public_id": new_team.public_id,
            "message": "New user and team created"
        }
        
    except Exception as e:
        db.rollback()
        log.exception("Error in google_auth endpoint")
        raise HTTPException(status_code=500, detail=f"Authentication failed: {str(e)}")

# ================================
# Public minimal preview endpoint
# ================================

@router.get("/public/users/{public_id}/preview", response_model=UserPreviewResponse)
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(OperationalError),
    before_sleep=before_sleep_log(user_retry_logger, logging.WARNING)
)
def get_user_preview(public_id: str, db: Session = Depends(get_db)):
    """
    Public endpoint returning minimal, non-sensitive data for rendering a blurred preview.
    Does not expose full answers, bento widgets, emails, or images.
    """
    log = new_logger("get_user_preview")
    log.info(f"Fetching public preview for user: {public_id}")
    try:
        user = db.query(WelcomepageUser).filter_by(public_id=public_id).first()
        if not user:
            log.info(f"Target user not found for preview: {public_id}")
            raise HTTPException(status_code=404, detail="User not found")

        team = user.team
        if not team:
            log.warning(f"User has no team for preview: {public_id}")
            raise HTTPException(status_code=404, detail="User not found")

        # Minimal display name: First name + last initial (if available)
        name = user.name or ""
        first, last = (name.split(" ", 1) + [""])[:2]
        display_name = f"{first} {last[:1] + '.' if last else ''}".strip()

        return UserPreviewResponse(
            public_id=user.public_id,
            display_name=display_name or "Welcomepage User",
            team_public_id=team.public_id,
        )
    except OperationalError:
        db.rollback()
        raise
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Non-retryable error in get_user_preview: {e}")
        raise HTTPException(status_code=500, detail="Internal error")

# ==============================================
# Ensure authenticated user exists in target team
# ==============================================

@router.post("/view/ensure-in-team", response_model=EnsureInTeamResponse)
def ensure_in_team(
    payload: EnsureInTeamRequest = Body(...),
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("USER", "ADMIN"))
):
    """
    Ensure the authenticated user has a Welcomepage user record in the same team
    as the target user being viewed. This is called AFTER full authentication.

    Rules:
    - If an authenticated user record already exists, do nothing and return success
      (we do not migrate cross-team users here).
    - If no record exists, create a new user in the target user's team using the
      authenticated identity (auth_email/role from JWT context is not persisted here;
      persistence should already be handled by auth flows). We create a minimal
      record with is_draft=True.
    """
    log = new_logger("ensure_in_team")
    requester_public_id = current_user.get('user_id') if isinstance(current_user, dict) else None
    requester_role = current_user.get('role') if isinstance(current_user, dict) else None
    log.info(f"Ensuring in-team for requester={requester_public_id} viewing target={payload.target_user_public_id}")

    try:
        # Lookup target user and their team
        target = db.query(WelcomepageUser).filter_by(public_id=payload.target_user_public_id).first()
        if not target:
            log.info(f"Target user not found: {payload.target_user_public_id}")
            raise HTTPException(status_code=404, detail="User not found")

        team = target.team
        if not team:
            log.warning(f"Target user has no team: {payload.target_user_public_id}")
            raise HTTPException(status_code=404, detail="User not found")

        # Check if requester has an existing record
        existing = db.query(WelcomepageUser).filter_by(public_id=requester_public_id).first()
        if existing:
            log.info(f"Requester already has a user record [{existing.public_id}] in team_id={existing.team_id}; no action")
            return EnsureInTeamResponse(success=True, team_public_id=team.public_id, user_public_id=existing.public_id)

        # Create a minimal user record in the target team
        new_user = WelcomepageUser(
            public_id=requester_public_id,
            name="",
            role="",
            auth_role=requester_role,
            team_id=team.id,
            is_draft=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        log.info(f"Created new user for requester in team {team.public_id}: {new_user.public_id}")
        return EnsureInTeamResponse(success=True, team_public_id=team.public_id, user_public_id=new_user.public_id)
    except OperationalError:
        db.rollback()
        raise
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        log.error(f"Non-retryable error in ensure_in_team: {e}")
        raise HTTPException(status_code=500, detail="Internal error")

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
    bento_widgets: str = Form(None),
    team_id: int = Form(None),
    team_public_id: str = Form(None),  # Support team assignment by public ID
    slack_user_id: str = Form(None),  # Preserve Slack user ID
    pronunciation_text: str = Form(None),  # Written pronunciation
    profile_photo: UploadFile = File(None),
    wave_gif: UploadFile = File(None),
    pronunciation_recording: UploadFile = File(None),
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("USER", "ADMIN", "PRE_SIGNUP"))
):
    log = new_logger("upsert_user")
    
    # Log the readable fields being passed to upsert_user (excluding file uploads)
    log.info(f"upsert_user called with: id={id}, public_id={public_id}, name={name}, role={role}, "
             f"auth_role={auth_role}, auth_email={auth_email}, location={location}, greeting={greeting}, "
             f"nickname={nickname}, hi_yall_text={hi_yall_text}, handwave_emoji={handwave_emoji}, "
             f"handwave_emoji_url={handwave_emoji_url}, selected_prompts={selected_prompts}, "
             f"answers={'[JSON data]' if answers else None}, team_id={team_id}, team_public_id={team_public_id}, "
             f"pronunciation_text={pronunciation_text}, has_profile_photo={profile_photo is not None}, "
             f"has_wave_gif={wave_gif is not None}, has_pronunciation_recording={pronunciation_recording is not None} "
             f"slack_user_id={slack_user_id}")
    
    # Step 1: Process all file uploads first and get URLs
    form_data = await request.form()
    
    # Handle profile photo upload
    profile_photo_url = None
    if profile_photo:
        photo_filename = f"{generate_file_id(public_id)}-profile-photo"
        content = await profile_photo.read()
        profile_photo_url = await upload_to_supabase_storage(
            file_content=content,
            filename=photo_filename,
            content_type=profile_photo.content_type or "image/jpeg"
        )
        log.info(f"Uploaded profile photo: {profile_photo_url}")
    
    # Handle wave video upload and conversion
    wave_gif_url = None
    if wave_gif:
        from services.wave_video_service import WaveVideoService
        wave_service = WaveVideoService()
        wave_gif_url = await wave_service.process_wave_video(wave_gif, public_id)
        log.info(f"Processed and uploaded wave video/gif: {wave_gif_url}")
    
    # Handle pronunciation recording upload
    pronunciation_recording_url = None
    if pronunciation_recording:
        audio_filename = f"{generate_file_id(public_id)}-pronunciation-audio"
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

    # Parse bento widgets JSON string if provided
    try:
        bento_widgets_list = json.loads(bento_widgets or "[]")
    except Exception as e:
        log.warning(f"Invalid bentoWidgets JSON: {bento_widgets!r}. Using empty list. Error: {e}")
        bento_widgets_list = []
    
    # Process Bento widget image uploads: keys like bento_widget_image_<widgetId>
    try:
        for field_name, file_data in form_data.items():
            if field_name.startswith("bento_widget_image_") and hasattr(file_data, 'filename') and file_data.filename:
                widget_id = field_name.replace("bento_widget_image_", "")
                log.info(f"Processing Bento widget image upload for widget id: {widget_id}")

                # Create a stable filename based on the user's public_id and widget id
                safe_widget_id = widget_id.replace("/", "_").replace("\\", "_").replace(":", "_")
                image_filename = f"{generate_file_id(public_id)}-bento-{safe_widget_id}"

                # Upload image to Supabase
                content = await file_data.read()
                image_url = await upload_to_supabase_storage(
                    file_content=content,
                    filename=image_filename,
                    content_type=file_data.content_type or "image/jpeg"
                )
                log.info(f"Uploaded Bento widget image for [{widget_id}]: {image_url}")

                # Inject URL (and file meta) back into the corresponding widget in bento_widgets_list
                try:
                    for w in bento_widgets_list:
                        if isinstance(w, dict) and w.get('id') == widget_id:
                            content_obj = (w.get('content') or {})
                            # Optional: include file metadata for client reference
                            content_obj['file'] = {
                                'filename': file_data.filename,
                                'contentType': file_data.content_type or 'image/jpeg',
                                'size': len(content),
                            }
                            content_obj['url'] = image_url
                            w['content'] = content_obj
                            break
                except Exception:
                    log.exception(f"Failed to inject Bento widget URL back into JSON for widget {widget_id}")
    except Exception:
        log.exception("Error while processing Bento widget image uploads")

    # Parse handwave_emoji JSON string if provided
    parsed_handwave_emoji = None
    if handwave_emoji:
        try:
            parsed_handwave_emoji = json.loads(handwave_emoji)
            log.info(f"Parsed handwave_emoji: {parsed_handwave_emoji}")
        except Exception as e:
            log.warning(f"Invalid handwave_emoji JSON: {handwave_emoji!r}. Using None. Error: {e}")
            parsed_handwave_emoji = None
    
    # Process dynamic prompt image uploads
    for field_name, file_data in form_data.items():
        if field_name.startswith("answer_image_") and hasattr(file_data, 'filename') and file_data.filename:
            # Extract prompt text from field name
            prompt_text = field_name.replace("answer_image_", "")
            log.info(f"Processing image upload for prompt: '{prompt_text}'")
            
            # Create safe filename
            safe_prompt_label = prompt_text.replace("?", "").replace("'", "").replace(" ", "_").replace(".", "").replace(",", "").replace("/", "_").replace("\\", "_").replace(":", "_").lower()
            image_filename = f"{generate_file_id(public_id)}-prompt-{safe_prompt_label}"
            
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
    
    # Step 3: Handle team assignment - extract from JWT if not provided in form data
    effective_team_id = team_id
    
    # If no team_id provided in form data, extract from JWT
    if effective_team_id is None:
        jwt_team_id = current_user.get('team_id')
        if jwt_team_id:
            log.info(f"Using team from JWT: {jwt_team_id}")
            # Convert team public_id from JWT to internal team_id
            from models.team import Team
            target_team = db.query(Team).filter_by(public_id=jwt_team_id).first()
            if target_team:
                effective_team_id = target_team.id
                log.info(f"Found team {jwt_team_id} with internal ID {effective_team_id}")
            else:
                log.error(f"Team not found for JWT team_id: {jwt_team_id}")
                raise HTTPException(status_code=404, detail="Team not found")
    
    # Handle explicit team_public_id parameter (for legacy support)
    elif team_public_id and not team_id:
        log.info(f"Looking up team by public_id: {team_public_id}")
        from models.team import Team
        target_team = db.query(Team).filter_by(public_id=team_public_id).first()
        if target_team:
            effective_team_id = target_team.id
            log.info(f"Found team {team_public_id} with internal ID {effective_team_id}")
        else:
            log.error(f"Team not found for public_id: {team_public_id}")
            raise HTTPException(status_code=404, detail="Team not found")
    
    # Step 4: Save complete user record with all URLs in one database operation
    db_user, user_identifier, temp_uuid = await run_in_threadpool(
        upsert_user_db_logic, id, public_id, name, role, auth_role, auth_email, location, greeting, nickname, hi_yall_text, parsed_handwave_emoji, handwave_emoji_url, selected_prompts, json.dumps(answers_dict), json.dumps(bento_widgets_list), effective_team_id, db, log, profile_photo_url, wave_gif_url, pronunciation_text, pronunciation_recording_url, slack_user_id, current_user
    )

    return WelcomepageUserDTO.model_validate(db_user)

@retry(
    stop=stop_after_attempt(5),  # Increased attempts for connection issues
    wait=wait_exponential(multiplier=1, min=2, max=15),  # Longer max wait for connection recovery
    retry=retry_if_exception_type((OperationalError, IntegrityError, DataError, DatabaseError)),  # Only retry database exceptions
    before_sleep=before_sleep_log(upsert_retry_logger, logging.WARNING)
)
def upsert_user_db_logic(
    id, public_id, name, role, auth_role, auth_email, location, greeting, nickname, hi_yall_text, handwave_emoji, handwave_emoji_url, selected_prompts, answers, bento_widgets, team_id, db, log, profile_photo_url=None, wave_gif_url=None, pronunciation_text=None, pronunciation_recording_url=None, slack_user_id=None, current_user=None
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
        # Parse bento widgets
        try:
            bento_widgets_list = json.loads(bento_widgets or "[]")
        except Exception as e:
            log.warning(f"Invalid bento_widgets: {bento_widgets!r}. Using empty list. Error: {e}")
            bento_widgets_list = []
        
        # Ensure answers_dict includes all selected prompts with proper structure
        for prompt in selected_prompts_list:
            if prompt not in answers_dict:
                answers_dict[prompt] = {"text": "", "image": None, "specialData": None}

        # Enforce that team_id is present (from form data or JWT)
        if team_id is None:
            raise HTTPException(status_code=422, detail="Team assignment failed - no team information available")

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
            
            # Defensive lookup: If still no user found, try looking up by slack_user_id
            # This handles re-registration after Slack uninstall/reinstall where the user
            # record still exists with the slack_user_id from the previous installation
            if db_user is None and slack_user_id and team_id:
                db_user = db.query(WelcomepageUser).filter_by(
                    slack_user_id=slack_user_id,
                    team_id=team_id
                ).first()
                if db_user:
                    log.info(f"Found existing user by slack_user_id: {slack_user_id} in team_id {team_id}, will update user {db_user.public_id}")
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
            db_user.bento_widgets = bento_widgets_list
            db_user.team_id = team_id
            # Preserve existing slack_user_id if none provided in request
            if slack_user_id is not None:
                db_user.slack_user_id = slack_user_id   
            
            # Update file URLs if provided
            if profile_photo_url:
                db_user.profile_photo_url = profile_photo_url
            if wave_gif_url:
                db_user.wave_gif_url = wave_gif_url
            if pronunciation_text is not None:
                db_user.pronunciation_text = pronunciation_text
            if pronunciation_recording_url:
                db_user.pronunciation_recording_url = pronunciation_recording_url
            
            # Set created_at if it's null (for existing records that were created before timestamps were implemented)
            if db_user.created_at is None:
                db_user.created_at = datetime.now(timezone.utc)
            
            # Update the timestamp for when this record was last modified
            db_user.updated_at = datetime.now(timezone.utc)
            
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
            effective_public_id = user_lookup_id if user_lookup_id else generate_short_id_with_collision_check(db, WelcomepageUser, "user")
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
                bento_widgets=bento_widgets_list,
                team_id=team_id,
                slack_user_id=slack_user_id,
                is_draft=True,
                profile_photo_url=profile_photo_url,
                wave_gif_url=wave_gif_url,
                pronunciation_text=pronunciation_text,
                pronunciation_recording_url=pronunciation_recording_url,

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
    except (OperationalError, Exception):
        # OperationalError and Exception are both in retry_if_exception_type - let them bubble up
        raise


@router.get("/users/{public_id}", response_model=WelcomepageUserDTO)
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(OperationalError),
    before_sleep=before_sleep_log(user_retry_logger, logging.WARNING)
)
def get_user(public_id: str, db: Session = Depends(get_db), current_user=Depends(require_roles("USER", "ADMIN", "PRE_SIGNUP"))):
    log = new_logger("get_user")
    log.info(f"Fetching user with public_id: {public_id}. Requesting user: {current_user.get('user_id')}, team: {current_user.get('team_id')}")
    
    try:
        # First, get the target user
        target_user = db.query(WelcomepageUser).filter_by(public_id=public_id).first()
        if not target_user:
            log.info(f"Target user not found: {public_id}")
            raise HTTPException(status_code=404, detail="User not found")
        
        # Get the requesting user's team information
        requesting_user_id = current_user.get('user_id')
        requesting_team_id = current_user.get('team_id')
        requesting_user_role = current_user.get('role')
        
        # Handle anonymous users (PRE_SIGNUP) who don't exist in database yet
        if requesting_user_role == 'PRE_SIGNUP':
            log.info(f"Anonymous user access: {requesting_user_id} with team {requesting_team_id}")
            
            # For anonymous users, we only need to verify team_id is provided
            if not requesting_team_id:
                log.error(f"SECURITY: Anonymous user JWT missing required team_id field. User: {requesting_user_id}")
                raise HTTPException(status_code=404, detail="User not found")
            
            # Get target user's team
            target_user_team = target_user.team
            if not target_user_team:
                log.error(f"Target user has no team: {public_id}")
                raise HTTPException(status_code=404, detail="User not found")
            
            # For anonymous users, compare JWT team_id with target user's team public_id
            if requesting_team_id != target_user_team.public_id:
                log.warning(f"Cross-team access attempt by anonymous user: requesting_team={requesting_team_id} tried to access target_user={public_id} (team_public_id={target_user_team.public_id})")
                raise HTTPException(status_code=404, detail="User not found")
            
            log.info(f"Anonymous user team access control passed: team {requesting_team_id}")
        
        else:
            # For authenticated users (USER, ADMIN), enforce full team-based access control
            if not requesting_team_id:
                log.error(f"SECURITY: JWT missing required team_id field. Requesting user: {requesting_user_id}. This indicates an invalid or malformed JWT.")
                raise HTTPException(status_code=404, detail="User not found")
            
            # Get requesting user's actual team from database for verification
            requesting_user = db.query(WelcomepageUser).filter_by(public_id=requesting_user_id).first()
            
            if not requesting_user:
                log.warning(f"Requesting user not found in database: {requesting_user_id}")
                raise HTTPException(status_code=401, detail="Invalid authentication")
            
            # Get team public IDs for comparison (JWT contains public IDs, not internal IDs)
            requesting_user_team = requesting_user.team
            target_user_team = target_user.team
            
            if not requesting_user_team or not target_user_team:
                log.error(f"Team data missing: requesting_user_team={requesting_user_team}, target_user_team={target_user_team}")
                raise HTTPException(status_code=404, detail="User not found")
            
            # Compare team PUBLIC IDs (not internal database IDs)
            if target_user_team.public_id != requesting_user_team.public_id:
                log.warning(f"Cross-team access attempt: requesting_user={requesting_user_id} (team_public_id={requesting_user_team.public_id}) tried to access target_user={public_id} (team_public_id={target_user_team.public_id})")
                raise HTTPException(status_code=404, detail="User not found")
            
            # Additional verification: JWT team_id should match requesting user's team public_id
            if requesting_team_id != requesting_user_team.public_id:
                log.error(f"JWT team_id mismatch: JWT contains team_id={requesting_team_id}, but user belongs to team_public_id={requesting_user_team.public_id}")
                raise HTTPException(status_code=401, detail="Invalid authentication")
            
            log.info(f"Authenticated user team access control passed: both users in team {requesting_user_team.public_id}")
        
        log.info(f"User access granted: {public_id}")
        
        # Create response data with team public ID
        user_data = target_user.__dict__.copy()
        user_data['team_public_id'] = target_user.team.public_id
        
        # Use model_validate with field validators handling data sanitization
        return WelcomepageUserDTO.model_validate(user_data)
        
    except OperationalError:
        db.rollback()
        raise  # trigger the retry
    except OperationalError:
        # These exceptions are handled by the @retry decorator - let them bubble up
        raise
    except Exception as e:
        # Only catch non-retryable exceptions here
        db.rollback()
        log.exception("Non-retryable database error in get_user.")
        raise HTTPException(status_code=500, detail="Database error. Please try again later.")

@router.get("/users/peer-data/{team_public_id}", response_model=PeerDataResponse)
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(OperationalError),
    before_sleep=before_sleep_log(user_retry_logger, logging.WARNING)
)
def get_peer_data(team_public_id: str, db: Session = Depends(get_db), current_user=Depends(require_roles("USER", "ADMIN", "PRE_SIGNUP"))):
    """
    Get peer data showing team member answers for each prompt.
    Queries database using team_public_id to get real team member data.
    """
    log = new_logger("get_peer_data")
    log.info(f"Fetching peer data for team_public_id: {team_public_id}")
    
    try:
        # Find team by team_public_id
        team = db.query(Team).filter_by(public_id=team_public_id).first()
        if not team:
            log.warning(f"Team not found for public_id: {team_public_id}")
            raise HTTPException(status_code=404, detail="Team not found")
        
        log.info(f"Found team: {team.organization_name} (id: {team.id})")
        
        # Get all users in that team
        team_members = db.query(WelcomepageUser).filter_by(team_id=team.id).all()
        log.info(f"Found {len(team_members)} team members")
        
        # Group answers by prompt question
        peer_data = {}
        total_members_with_answers = 0
        
        for member in team_members:
            if member.answers:  # answers is a JSON field
                try:
                    # Handle both string and dict cases for answers field
                    if isinstance(member.answers, str):
                        answers_data = json.loads(member.answers)
                    else:
                        answers_data = member.answers
                    
                    member_has_answers = False
                    for prompt, answer in answers_data.items():
                        # Handle both string and dict answers
                        answer_text = None
                        if isinstance(answer, str):
                            answer_text = answer.strip() if answer else None
                        elif isinstance(answer, dict):
                            # Extract text from dict format (e.g., {"text": "answer", "image": "..."})
                            answer_text = answer.get('text', '').strip() if answer.get('text') else None
                        
                        if answer_text:  # Only include non-empty answers
                            if prompt not in peer_data:
                                peer_data[prompt] = []
                            peer_data[prompt].append(PeerAnswer(
                                name=member.name,
                                avatar=member.profile_photo_url or "/placeholder.svg?height=100&width=100",
                                answer=answer_text,
                                user_id=member.public_id  # Optional field for future use
                            ))
                            member_has_answers = True
                    
                    if member_has_answers:
                        total_members_with_answers += 1
                        
                except (json.JSONDecodeError, TypeError) as e:
                    log.warning(f"Failed to parse answers for member {member.name} (id: {member.id}): {e}")
                    continue
        
        log.info(f"Returning peer data with {len(peer_data)} prompts and {total_members_with_answers} members with answers")
        
        return PeerDataResponse(
            peer_data=peer_data,
            team_id=team_public_id,
            total_prompts=len(peer_data),
            total_members=total_members_with_answers
        )
        
    except OperationalError:
        db.rollback()
        raise  # trigger the retry
    except OperationalError:
        # These exceptions are handled by the @retry decorator - let them bubble up
        raise
    except Exception as e:
        # Only catch non-retryable exceptions here
        db.rollback()
        log.exception("Non-retryable database error in get_peer_data.")
        raise HTTPException(status_code=500, detail="Database error. Please try again later.")
    
    # LEGACY SAMPLE DATA - DO NOT DELETE
    # This hardcoded data is preserved for reference and testing purposes
    # sample_peer_data = {
    #     "What's your superpower at work?": [
    #         PeerAnswer(
    #             name="Alex Chen",
    #             avatar="/placeholder.svg?height=100&width=100",
    #             answer="I can turn complex problems into simple, actionable steps. It helps the team move forward when we're stuck on challenging projects."
    #         ),
    #         PeerAnswer(
    #             name="Jamie Taylor",
    #             avatar="/placeholder.svg?height=100&width=100",
    #             answer="I'm the team's documentation wizard! I make sure our knowledge is captured and accessible to everyone."
    #         ),
    #         PeerAnswer(
    #             name="Morgan Lee",
    #             avatar="/placeholder.svg?height=100&width=100",
    #             answer="Definitely my ability to bring different perspectives together. I can usually find common ground when opinions differ."
    #         )
    #     ],
    #     "What's something unexpected about you?": [
    #         PeerAnswer(
    #             name="Sam Rivera",
    #             avatar="/placeholder.svg?height=100&width=100",
    #             answer="I used to be a professional chess player before getting into tech. The strategic thinking definitely helps in my current role!"
    #         ),
    #         PeerAnswer(
    #             name="Taylor Kim",
    #             avatar="/placeholder.svg?height=100&width=100",
    #             answer="I can speak five languages! I grew up in an international community and picked them up along the way."
    #         )
    #     ],
    #     "What's your favorite way to spend a weekend?": [
    #         PeerAnswer(
    #             name="Jordan Patel",
    #             avatar="/placeholder.svg?height=100&width=100",
    #             answer="Hiking with my dog and then trying a new restaurant in the evening. Perfect balance of activity and relaxation!"
    #         ),
    #         PeerAnswer(
    #             name="Casey Wong",
    #             avatar="/placeholder.svg?height=100&width=100",
    #             answer="I'm part of a community garden and spend most weekends there. It's my meditation and social time rolled into one."
    #         ),
    #         PeerAnswer(
    #             name="Riley Johnson",
    #             avatar="/placeholder.svg?height=100&width=100",
    #             answer="Board game marathons with friends! We're currently obsessed with strategy games that take hours to play."
    #         ),
    #         PeerAnswer(
    #             name="Avery Smith",
    #             avatar="/placeholder.svg?height=100&width=100",
    #             answer="Exploring local museums and art galleries. There's always something new to discover even in familiar places."
    #         )
    #     ],
    #     "What's your go-to productivity hack?": [
    #         PeerAnswer(
    #             name="Quinn Martinez",
    #             avatar="/placeholder.svg?height=100&width=100",
    #             answer="Time blocking my calendar with specific tasks rather than general 'work time'. It helps me stay focused and track progress."
    #         ),
    #         PeerAnswer(
    #             name="Blake Thompson",
    #             avatar="/placeholder.svg?height=100&width=100",
    #             answer="The Pomodoro Technique! 25 minutes of focused work followed by a 5-minute break. It's amazing how much I can accomplish."
    #         )
    #     ]
    # }
