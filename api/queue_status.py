"""
API endpoints for viewing and managing queued pages
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models.welcomepage_user import WelcomepageUser
from models.team import Team
from utils.logger_factory import new_logger
from utils.jwt_auth import require_roles
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

router = APIRouter()
log = new_logger("queue_status")


class QueuedPageInfo(BaseModel):
    user_public_id: str
    user_name: str
    queued_at: str
    days_queued: int


class QueueStatusResponse(BaseModel):
    team_public_id: str
    team_name: str
    published_count: int
    queued_count: int
    queued_pages: List[QueuedPageInfo]
    has_payment_method: bool


@router.get("/queue/status/{team_public_id}", response_model=QueueStatusResponse)
async def get_queue_status(
    team_public_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("ADMIN"))
):
    """
    Get queue status for a team
    
    Shows:
    - Number of published pages
    - Number of queued pages
    - Details of each queued page
    - Whether team has payment method
    
    Only ADMIN users can view queue status
    """
    log.info(f"Fetching queue status for team {team_public_id}")
    
    # Verify user has access to this team
    requesting_team_id = current_user.get('team_id')
    if requesting_team_id != team_public_id:
        log.warning(f"User from team {requesting_team_id} tried to access queue for team {team_public_id}")
        raise HTTPException(status_code=403, detail="Access denied to this team")
    
    # Get team
    team = db.query(Team).filter_by(public_id=team_public_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    
    # Count published pages (not drafts, not queued)
    published_count = db.query(WelcomepageUser).filter(
        WelcomepageUser.team_id == team.id,
        WelcomepageUser.is_draft == False,
        WelcomepageUser.publish_queued == False
    ).count()
    
    # Find queued pages
    queued_users = db.query(WelcomepageUser).filter(
        WelcomepageUser.team_id == team.id,
        WelcomepageUser.publish_queued == True
    ).order_by(WelcomepageUser.queued_at).all()
    
    # Build queued page info
    queued_pages = []
    now = datetime.now()
    for user in queued_users:
        days_queued = 0
        if user.queued_at:
            # Handle both timezone-aware and naive datetimes
            queued_at_aware = user.queued_at if user.queued_at.tzinfo else user.queued_at.replace(tzinfo=None)
            now_for_comparison = now if queued_at_aware.tzinfo is None else now.replace(tzinfo=None)
            delta = now_for_comparison - queued_at_aware
            days_queued = delta.days
        
        queued_pages.append(QueuedPageInfo(
            user_public_id=user.public_id,
            user_name=user.name,
            queued_at=user.queued_at.isoformat() if user.queued_at else "",
            days_queued=days_queued
        ))
    
    return QueueStatusResponse(
        team_public_id=team.public_id,
        team_name=team.organization_name,
        published_count=published_count,
        queued_count=len(queued_pages),
        queued_pages=queued_pages,
        has_payment_method=bool(team.stripe_customer_id)
    )


def count_published_pages(team_id: int, db: Session) -> int:
    """
    Helper function to count published pages for a team
    
    Args:
        team_id: Internal team ID
        db: Database session
        
    Returns:
        Count of published pages (is_draft=False, publish_queued=False)
    """
    return db.query(WelcomepageUser).filter(
        WelcomepageUser.team_id == team_id,
        WelcomepageUser.is_draft == False,
        WelcomepageUser.publish_queued == False
    ).count()

