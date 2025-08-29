from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone

from database import get_db
from models.welcomepage_user import WelcomepageUser
from utils.jwt_auth import require_roles
from utils.logger_factory import new_logger

router = APIRouter()


class CommentCreateRequest(BaseModel):
    target_user_id: str
    content: str
    prompt_index: Optional[int] = None


class CommentResponse(BaseModel):
    id: str
    content: str
    author_public_id: str
    timestamp: str
    prompt_index: Optional[int] = None
    # Added to align with reactions payload shape for display
    user: Optional[str] = None
    userId: Optional[str] = None

@router.post("/")
async def create_comment(
    request: CommentCreateRequest,
    db: Session = Depends(get_db),
    current_user = Depends(require_roles("USER", "ADMIN", "PRE_SIGNUP"))
):
    log = new_logger("create_comment")
    log.info(f"create_comment: actor={current_user.get('user_id')} target={request.target_user_id}")

    try:
        # Fetch the target user (no row lock; keep transaction short)
        target_user = (
            db.query(WelcomepageUser)
            .filter(WelcomepageUser.public_id == request.target_user_id)
            .first()
        )
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")

        actor_team = current_user.get("team_id") if isinstance(current_user, dict) else None
        target_team = target_user.team.public_id if target_user.team else None
        if actor_team != target_team:
            log.warning(f"Access denied for comments write: actor_team={actor_team} target_team={target_team}")
            raise HTTPException(status_code=403, detail="Access denied")

        comments: List[Dict[str, Any]] = target_user.page_comments or []

        # Build new comment
        now = datetime.now(timezone.utc)
        comment_id = f"{current_user.get('user_id')}_{int(now.timestamp())}"
        new_comment: Dict[str, Any] = {
            "id": comment_id,
            "content": request.content,
            "author_public_id": current_user.get("user_id"),
            "timestamp": now.isoformat(),
        }
        # Store display name fields similar to reactions for consistent frontend consumption
        display_name = current_user.get("name", "Unknown") if isinstance(current_user, dict) else "Unknown"
        new_comment["user"] = display_name
        new_comment["userId"] = current_user.get("user_id") if isinstance(current_user, dict) else None
        if request.prompt_index is not None:
            new_comment["prompt_index"] = request.prompt_index

        comments.append(new_comment)
        target_user.page_comments = comments
        target_user.updated_at = now

        # Mark JSON field modified
        flag_modified(target_user, "page_comments")

        db.commit()
        db.refresh(target_user)

        log.info("Comment added successfully")
        return {"success": True, "comment": new_comment}

    except HTTPException:
        raise
    except Exception as e:
        log.exception("Failed to create comment")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create comment: {str(e)}")
