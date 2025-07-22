from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
import random
from database import get_db
from utils.logger_factory import new_logger

from models.verification_code import VerificationCode


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

    verification_code = VerificationCode(
        email=email,
        code=code,
        public_id=payload.public_id if payload.public_id else None,
        created_at=now,
        expires_at=expires_at,
        used=False,
    )
    log.info(f"Verification code generated [{verification_code.to_dict()}]")
    db.add(verification_code)
    db.commit()
    db.refresh(verification_code)
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
    db.commit()
    db.refresh(verification_code)
    log.info(f"Verification code verified [{verification_code.to_dict()}]")
    return {"success": True}

@router.post("/verify_code/")
def verify_code(payload: 'VerificationRequest', db: Session = Depends(get_db)):
    log = new_logger("verify_code")
    log.info(f"Verifying code for {payload.email} [{payload.code}]")
    return verify_code_with_retry(payload, db, log)

