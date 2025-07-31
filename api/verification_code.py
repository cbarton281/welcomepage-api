from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
import random
from database import get_db
from utils.logger_factory import new_logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log

from models.verification_code import VerificationCode
from models.team import Team
from models.welcomepage_user import WelcomepageUser


router = APIRouter()

CODE_EXPIRY_MINUTES = 10

from pydantic import BaseModel
from utils.jwt_auth import require_roles

from typing import Optional

class GenerateCodeRequest(BaseModel):
    email: str
    public_id: Optional[str] = None

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log
import logging
from sqlalchemy.exc import OperationalError

verification_retry_logger = new_logger("verification_email_retry")

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(OperationalError),
    before_sleep=before_sleep_log(verification_retry_logger, logging.WARNING)
)
def generate_code_with_retry(payload: GenerateCodeRequest, db: Session, log):
    email = payload.email
    code = str(random.randint(100000, 999999))
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=CODE_EXPIRY_MINUTES)

    db.query(VerificationCode).filter_by(email=email, used=False).update({"used": True})

    # Check if user already exists by email
    existing_user = db.query(WelcomepageUser).filter_by(auth_email=email).first()

    if existing_user:
        # Use existing user's correct public_id
        verification_public_id = existing_user.public_id
    else:
        # Use anonymous cookie data for new users
        verification_public_id = payload.public_id

    verification_code = VerificationCode(
        email=email,
        code=code,
        public_id=verification_public_id,
        created_at=now,
        expires_at=expires_at,
        used=False,
    )
    log.info(f"Verification code generated [{verification_code.to_dict()}]")
    try:
        db.add(verification_code)
        db.commit()
        db.refresh(verification_code)
    except OperationalError as e:
        db.rollback()
        log.exception("OperationalError in verify_code_with_retry, will retry.")
        raise  # trigger the retry
    except Exception as e:
        db.rollback()
        log.exception("Database commit/refresh failed in update_auth_fields.")
        raise HTTPException(status_code=500, detail="Database error. Please try again later.")
    return verification_code, expires_at, code

@router.post("/generate_verification_email/")
def generate_verification_email(
    payload: GenerateCodeRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("USER", "ADMIN", "PRE_SIGNUP"))
):
    log = new_logger("generate_verification_email")
    log.info(f"Generating verification code for {payload.email}")
    verification_code, expires_at, code = generate_code_with_retry(payload, db, log)
    # Send the verification email
    from api.send_email import send_verification_email
    try:
        send_verification_email(payload.email, code)
        log.info(f"Verification email sent to {payload.email}")
    except Exception as e:
        log.error(f"Failed to send verification email: {e}")
        raise HTTPException(status_code=500, detail="Failed to send verification email.")
    return {"email": payload.email, "expires_at": expires_at.isoformat(), "message": "Verification email sent."}



from pydantic import BaseModel

class VerificationRequest(BaseModel):
    email: str
    code: str

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(OperationalError),
    before_sleep=before_sleep_log(verification_retry_logger, logging.WARNING)
)
def verify_code_with_retry(payload: 'VerificationRequest', db: Session, log):
    email = payload.email
    code = payload.code
    now = datetime.now(timezone.utc)
    verification_code = db.query(VerificationCode).filter_by(email=email, code=code, used=False).first()
    log.info(f"Verification code found [{verification_code.to_dict()}]" if verification_code else "Verification code not found")
    if not verification_code:
        log.info(f"Verification code not found for {email} [{code}]")
        raise HTTPException(status_code=400, detail="Invalid or already used code.")
    if verification_code.expires_at < now:
        log.info(f"Verification code expired for {email} [{code}]")
        raise HTTPException(status_code=400, detail="Code expired.")
    verification_code.used = True
    try:
        db.commit()
        db.refresh(verification_code)
    except OperationalError as e:
        db.rollback()
        log.exception("OperationalError in verify_code_with_retry, will retry.")
        raise  # trigger the retry
    except Exception as e:
        db.rollback()
        log.exception("Database commit/refresh failed in verify_code_with_retry.")
        raise HTTPException(status_code=500, detail="Database error. Please try again later.")
    log.info(f"Verification code verified [{verification_code.to_dict()}]")

    public_id = verification_code.public_id
    from models.welcomepage_user import WelcomepageUser
    user = None
    # Prefer email lookup if present, else use public_id
    log.info(f"Verifying user using email [{verification_code.email}] if present, else using public_id [{public_id}]")
    if verification_code.email:
        user = db.query(WelcomepageUser).filter_by(auth_email=verification_code.email).first()
        if not user and public_id:
            log.info(f"No user found for email [{verification_code.email}], trying public_id [{public_id}]")
            user = db.query(WelcomepageUser).filter_by(public_id=public_id).first()
    if not user:
        log.info(f"User not found for this verification code [{verification_code.to_dict()}]")
        raise HTTPException(status_code=404, detail="User not found for this verification code.")
    log.info(f"User found [{user.public_id}, {user.role}, {user.name}, {user.auth_email}, {user.auth_role}]")
    
    team_public_id = None
    if user.team_id:
        team = db.query(Team).filter_by(id=user.team_id).first()
        team_public_id = team.public_id
    
    auth_role = user.auth_role if user.auth_role else "PRE_SIGNUP"
    user_public_id = user.public_id if user.public_id else public_id
    return {"success": True, "public_id": user_public_id, "auth_role": auth_role, "team_public_id": team_public_id}

@router.post("/verify_code/")
def verify_code(payload: 'VerificationRequest', db: Session = Depends(get_db)):
    log = new_logger("verify_code")
    log.info(f"Verifying code for {payload.email} [{payload.code}]")
    return verify_code_with_retry(payload, db, log)

