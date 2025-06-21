from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from models.welcomepage_user import WelcomepageUser
from schemas.welcomepage_user import WelcomepageUserDTO
from utils.jwt_auth import require_roles
from app import get_db
from utils.logger_factory import new_logger
import logging

logging.basicConfig(level=logging.INFO)

router = APIRouter(prefix="/api/user", tags=["user"])

@router.post("/", response_model=WelcomepageUserDTO)
def create_user(
    user: WelcomepageUserDTO,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("USER", "ADMIN"))
):
    log = new_logger("create_user")
    log.info("endpoint invoked")
    log.info(f"Received user object: {user.json()}")
    db_user = WelcomepageUser(username=user.username, email=user.email)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return WelcomepageUserDTO.from_model(db_user)
