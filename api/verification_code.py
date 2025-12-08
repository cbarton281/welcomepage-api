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
    intended_auth_role: Optional[str] = "USER"  # Default to USER role

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
        intended_auth_role=payload.intended_auth_role,  # Store intended role
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
    
    # Domain enforcement: prevent sending codes to disallowed domains
    try:
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

        # Determine team for enforcement
        target_team = None
        # 1) If user already exists by email, use that user's team
        existing_user_by_email = db.query(WelcomepageUser).filter_by(auth_email=payload.email).first()
        if existing_user_by_email and existing_user_by_email.team_id:
            target_team = db.query(Team).filter_by(id=existing_user_by_email.team_id).first()
        # 2) Else try current_user token's team_id (public id)
        if target_team is None:
            jwt_team_public_id = current_user.get('team_id') if isinstance(current_user, dict) else None
            if jwt_team_public_id:
                target_team = db.query(Team).filter_by(public_id=jwt_team_public_id).first()
        # 3) Else try payload.public_id
        if target_team is None and payload.public_id:
            cookie_user = db.query(WelcomepageUser).filter_by(public_id=payload.public_id).first()
            if cookie_user and cookie_user.team_id:
                target_team = db.query(Team).filter_by(id=cookie_user.team_id).first()

        if target_team and target_team.security_settings:
            settings = target_team.security_settings or {}
            if bool(settings.get('domain_check_enabled')):
                domain = _normalize_email_domain(payload.email)
                allowed_list = settings.get('allowed_domains') or []
                if not _domain_allowed(domain, allowed_list):
                    log.warning(f"Blocked verification email due to domain policy. domain={domain}, team={target_team.public_id}")
                    raise HTTPException(status_code=403, detail="Email domain is not allowed for this team.")
    except HTTPException:
        raise
    except Exception:
        log.exception("Error during domain policy check in generate_verification_email")
        # Fail closed? Prefer safe default: if we cannot validate, block to avoid bypassing policy
        raise HTTPException(status_code=500, detail="Unable to process verification request.")
    verification_code, expires_at, code = generate_code_with_retry(payload, db, log)
    
    should_send_email = False
    user_type = "unknown"
    
    # Check if user exists by email (returning user)
    existing_user_by_email = db.query(WelcomepageUser).filter_by(auth_email=payload.email).first()
    
    if existing_user_by_email:
        # Returning user who already has auth_email set
        should_send_email = True
        user_type = "returning_user"
        log.info(f"Found returning user with auth_email: {payload.email}")
    elif payload.public_id:
        # Check if this is a legitimate new user (has public_id but no auth_email yet)
        potential_new_user = db.query(WelcomepageUser).filter_by(public_id=payload.public_id).first()
        if potential_new_user and not potential_new_user.auth_email:
            # This is a legitimate new user going through signup
            should_send_email = True
            user_type = "new_user"
            log.info(f"Found new user for signup: {payload.email} (public_id: {payload.public_id})")
        else:
            if potential_new_user:
                log.info(f"User exists but already has auth_email: {potential_new_user.auth_email}")
            else:
                log.info(f"No user found for public_id: {payload.public_id}")
                # Check if this is a PRE_SIGNUP user with team_id (team invitation signup flow)
                user_role = current_user.get('role') if isinstance(current_user, dict) else None
                jwt_team_id = current_user.get('team_id') if isinstance(current_user, dict) else None
                if user_role == 'PRE_SIGNUP' and jwt_team_id:
                    # This is a legitimate team invitation signup - create user if it doesn't exist
                    target_team = db.query(Team).filter_by(public_id=jwt_team_id).first()
                    if target_team:
                        # Check team signup limits before creating user
                        from utils.team_limits import check_team_signup_allowed
                        is_allowed, reason = check_team_signup_allowed(db, target_team.id)
                        if not is_allowed:
                            log.warning(f"Team signup blocked for team {jwt_team_id}: {reason}")
                            raise HTTPException(status_code=403, detail=reason)
                        
                        # Create user record for team invitation signup
                        new_user = WelcomepageUser(
                            public_id=payload.public_id,
                            name="",
                            role="",
                            auth_role="PRE_SIGNUP",
                            auth_email=None,  # Will be set after email verification
                            team_id=target_team.id,
                            is_draft=True,
                            created_at=datetime.now(timezone.utc),
                            updated_at=datetime.now(timezone.utc),
                        )
                        db.add(new_user)
                        try:
                            db.commit()
                            db.refresh(new_user)
                            log.info(f"Created user record for PRE_SIGNUP team invitation signup: {payload.email} (public_id: {payload.public_id}, team: {jwt_team_id})")
                        except Exception as e:
                            db.rollback()
                            # If user already exists (race condition), that's fine - continue
                            existing_user = db.query(WelcomepageUser).filter_by(public_id=payload.public_id).first()
                            if existing_user:
                                log.info(f"User already exists (race condition): {payload.public_id}")
                            else:
                                log.exception(f"Failed to create user record: {e}")
                                raise HTTPException(status_code=500, detail="Failed to create user record.")
                        
                        should_send_email = True
                        user_type = "team_invitation_signup"
                        log.info(f"PRE_SIGNUP user with team_id {jwt_team_id} - sending verification email for team invitation signup: {payload.email}")
                    else:
                        log.warning(f"Team not found for team_id: {jwt_team_id}")
                        raise HTTPException(status_code=404, detail="Team not found")
    else:
        log.info(f"No public_id provided for email: {payload.email}")
    
    if should_send_email:
        # Send the verification email
        from api.send_email import send_verification_email
        try:
            send_verification_email(payload.email, code)
            log.info(f"Verification email sent to {user_type}: {payload.email}")
        except Exception as e:
            log.error(f"Failed to send verification email: {e}")
            raise HTTPException(status_code=500, detail="Failed to send verification email.")
    else:
        log.info(f"No legitimate user found for {payload.email} - verification code generated but no email sent")
        # Add artificial delay to match email sending time for legitimate users
        # This prevents timing attacks and makes behavior indistinguishable
        import time
        time.sleep(2)  # 2 second delay to match typical email sending time
    
    # Always return 200 with same response regardless of user registration status
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
    
    # Domain enforcement at verification stage (defense in depth)
    try:
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

        team = db.query(Team).filter_by(id=user.team_id).first() if user.team_id else None
        if team and team.security_settings and bool(team.security_settings.get('domain_check_enabled')):
            domain = _normalize_email_domain(verification_code.email)
            if not _domain_allowed(domain, team.security_settings.get('allowed_domains') or []):
                log.warning(f"Blocked code verification due to domain policy. domain={domain}, team={team.public_id}")
                raise HTTPException(status_code=403, detail="Email domain is not allowed for this team.")
    except HTTPException:
        raise
    except Exception:
        log.exception("Error during domain policy check in verify_code_with_retry")
        raise HTTPException(status_code=500, detail="Unable to verify code at this time.")
    
    team_public_id = None
    team = None
    if user.team_id:
        team = db.query(Team).filter_by(id=user.team_id).first()
        if team:
            team_public_id = team.public_id
    
    auth_role = None
    if user.auth_role and user.auth_role != "PRE_SIGNUP":
        # User already has a non-PRE_SIGNUP role, keep it
        auth_role = user.auth_role
    elif verification_code.intended_auth_role:
        # Use intended role from verification code
        auth_role = verification_code.intended_auth_role
    elif team:
        # Original behavior: Check if user is the first user to verify in the team (team creator)
        # Count users who have already verified (have auth_email) excluding the current user
        verified_users_count = db.query(WelcomepageUser).filter(
            WelcomepageUser.team_id == team.id,
            WelcomepageUser.auth_email.isnot(None),
            WelcomepageUser.auth_email != '',
            WelcomepageUser.public_id != user.public_id  # Exclude current user
        ).count()
        
        if verified_users_count == 0:
            # This is the first user to verify in this team - they're the team creator
            log.info(f"User {user.public_id} is the first verified user in team {team.public_id} - assigning ADMIN role")
            auth_role = "ADMIN"
        else:
            # Not the first user to verify - regular USER role
            log.info(f"User {user.public_id} is not the first verified user in team {team.public_id} ({verified_users_count} already verified) - assigning USER role")
            auth_role = "USER"
    else:
        # No team context - default to PRE_SIGNUP (shouldn't happen in normal flow)
        auth_role = "PRE_SIGNUP"
    
    user_public_id = user.public_id if user.public_id else public_id
    
    log.info(f"Returning auth_role: {auth_role} (intended: {verification_code.intended_auth_role}, current: {user.auth_role}, team: {team_public_id if team else None})")
    return {"success": True, "public_id": user_public_id, "auth_role": auth_role, "team_public_id": team_public_id}

@router.post("/verify_code/")
def verify_code(payload: 'VerificationRequest', db: Session = Depends(get_db)):
    log = new_logger("verify_code")
    log.info(f"Verifying code for {payload.email} [{payload.code}]")
    return verify_code_with_retry(payload, db, log)

