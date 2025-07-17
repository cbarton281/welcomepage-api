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

class GenerateCodeRequest(BaseModel):
    email: str

@router.post("/generate_verification_email/")
def generate_verification_email(
    payload: GenerateCodeRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("USER", "ADMIN", "PRE_SIGNUP"))
):
    email = payload.email
    log = new_logger("generate_verification_email")
    log.info(f"Generating verification code for {email}")

    code = str(random.randint(100000, 999999))
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=CODE_EXPIRY_MINUTES)

    # Optionally: Invalidate previous codes for this email
    db.query(VerificationCode).filter_by(email=email, used=False).update({"used": True})

    verification_code = VerificationCode(
        email=email,
        code=code,
        created_at=now,
        expires_at=expires_at,
        used=False,
    )
    log.info(f"Verification code generated [{verification_code.to_dict()}]")
    db.add(verification_code)
    db.commit()
    db.refresh(verification_code)

    # Send the verification email
    from api.send_email import send_verification_email
    try:
        send_verification_email(email, code)
        log.info(f"Verification email sent to {email}")
    except Exception as e:
        log.error(f"Failed to send verification email: {e}")
        raise HTTPException(status_code=500, detail="Failed to send verification email.")

    return {"email": email, "expires_at": expires_at.isoformat(), "message": "Verification email sent."}


from pydantic import BaseModel

class VerificationRequest(BaseModel):
    email: str
    code: str

@router.post("/verify_code/")
def verify_code(payload: VerificationRequest, db: Session = Depends(get_db)):
    email = payload.email
    code = payload.code
    log = new_logger("verify_code")
    log.info(f"Verifying code for {email} [{code}]")
    now = datetime.now(timezone.utc)
    verification_code = db.query(VerificationCode).filter_by(email=email, code=code, used=False).first()
    if not verification_code:
        raise HTTPException(status_code=400, detail="Invalid or already used code.")
    if verification_code.expires_at < now:
        raise HTTPException(status_code=400, detail="Code expired.")
    verification_code.used = True
    db.commit()
    log.info(f"Verification code verified [{verification_code.to_dict()}]")
    return {"success": True}

