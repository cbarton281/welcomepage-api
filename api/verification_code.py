from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
import random
from database import get_db
from utils.logger_factory import new_logger

from models.verification_code import VerificationCode


router = APIRouter()

CODE_EXPIRY_MINUTES = 10

@router.post("/generate_verification_code/")
def generate_verification_code(email: str, db: Session = Depends(get_db)):

    log = new_logger("generate_verification_code")
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
    return {"email": email, "code": code, "expires_at": expires_at.isoformat()}

@router.post("/verify_code/")
def verify_code(email: str, code: str, db: Session = Depends(get_db)):
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
