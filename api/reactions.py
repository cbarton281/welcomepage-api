from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
from models.welcomepage_user import WelcomepageUser
from schemas.welcomepage_user import Reaction
from pydantic import BaseModel
from typing import Dict, Any
import json
from datetime import datetime, timezone
from utils.jwt_auth import require_roles
from utils.logger_factory import new_logger
    
router = APIRouter()

class AddReactionRequest(BaseModel):
    target_user_id: str
    prompt_key: str
    emoji: str

class RemoveReactionRequest(BaseModel):
    target_user_id: str
    prompt_key: str
    reaction_id: str

@router.post("/add")
async def add_reaction(
    request: AddReactionRequest,
    db: Session = Depends(get_db),
    current_user = Depends(require_roles("USER", "ADMIN"))
):
    """Add a reaction to a specific prompt answer"""
    log = new_logger("add_reaction")
    
    # Log the reaction information being posted
    log.info(f"add_reaction called: poster_id={current_user.get('user_id')}, "
             f"target_user_id={request.target_user_id}, prompt_key={request.prompt_key}, "
             f"emoji={request.emoji}, poster_role={current_user.get('role')}")
    
    try:
        # Get the target user whose page is being reacted to (no row lock; keep transactions short)
        target_user = (
            db.query(WelcomepageUser)
            .filter(WelcomepageUser.public_id == request.target_user_id)
            .first()
        )
        
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        # Enforce team access: user can only react within their own team
        cu_team_public_id = current_user.get('team_id') if isinstance(current_user, dict) else None
        target_team_public_id = target_user.team.public_id if target_user.team else None
        if cu_team_public_id != target_team_public_id:
            log.warning(f"Team access denied: actor_team={cu_team_public_id} target_team={target_team_public_id}")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        
        # Prevent users from reacting to their own page
        current_user_id = current_user.get('user_id') if isinstance(current_user, dict) else None
        if current_user_id == request.target_user_id:
            log.warning(f"User attempted to react to their own page: {current_user_id}")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot react to your own page")

        
        # Parse existing answers
        answers = target_user.answers or {}
        
        # Ensure the prompt exists in answers
        if request.prompt_key not in answers:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Prompt not found in user's answers"
            )
        
        # Initialize reactions array if it doesn't exist or is None
        if 'reactions' not in answers[request.prompt_key] or answers[request.prompt_key]['reactions'] is None:
            answers[request.prompt_key]['reactions'] = []
        
        # Check if user already reacted with this emoji to prevent duplicates
        existing_reactions = answers[request.prompt_key]['reactions']
        # Extra safety check to ensure existing_reactions is a list
        if existing_reactions is None:
            existing_reactions = []
            answers[request.prompt_key]['reactions'] = []
        user_existing_reaction = next(
            (r for r in existing_reactions 
             if r.get('userId') == current_user.get('user_id') and r.get('emoji') == request.emoji),
            None
        )
        
        if user_existing_reaction:
            log.info("User has already reacted with this emoji")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User has already reacted with this emoji"
            )
        
        # Get the reacting user's name from the database
        current_user_id = current_user.get('user_id') if isinstance(current_user, dict) else None
        reacting_user = None
        reacting_user_name = 'Anonymous User'
        
        if current_user_id:
            reacting_user = (
                db.query(WelcomepageUser)
                .filter(WelcomepageUser.public_id == current_user_id)
                .first()
            )
            if reacting_user and reacting_user.name:
                reacting_user_name = reacting_user.name
            else:
                log.warning(f"Could not find user or name for user_id: {current_user_id}")
        
        log.info(f"Reacting user name: {reacting_user_name}")
        
        # Create new reaction
        new_reaction = {
            'id': f"{current_user.get('user_id')}_{request.emoji}_{int(datetime.now(timezone.utc).timestamp())}",
            'emoji': request.emoji,
            'user': reacting_user_name,
            'userId': current_user.get('user_id'),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        
        # Add the reaction
        answers[request.prompt_key]['reactions'].append(new_reaction)
        log.info(f"Added reaction to answers: {new_reaction}")
        
        # Update the user's answers
        target_user.answers = answers
        target_user.updated_at = datetime.now(timezone.utc)
        
        # Explicitly mark the answers field as modified for SQLAlchemy
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(target_user, 'answers')
        
        log.info(f"Updated target_user.answers for user {target_user.public_id}")
        log.info(f"Marked answers field as modified for SQLAlchemy")
        
        # Commit to database
        log.info("Attempting to commit to database...")
        db.commit()
        log.info("Database commit successful")
        
        db.refresh(target_user)
        log.info(f"Database refresh successful. Final answers: {target_user.answers}")
        
        return {
            "success": True,
            "reaction": new_reaction,
            "message": "Reaction added successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Exception in add_reaction")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add reaction: {str(e)}"
        )

@router.post("/remove")
async def remove_reaction(
    request: RemoveReactionRequest,
    db: Session = Depends(get_db),
    current_user = Depends(require_roles("USER", "ADMIN"))
):
    log = new_logger("remove_reaction")
    try:
        # Get the target user (no row lock)
        target_user = (
            db.query(WelcomepageUser)
            .filter(WelcomepageUser.public_id == request.target_user_id)
            .first()
        )
        
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        # Enforce team access: user can only modify within their own team
        cu_team_public_id = current_user.get('team_id') if isinstance(current_user, dict) else None
        target_team_public_id = target_user.team.public_id if target_user.team else None
        if cu_team_public_id != target_team_public_id:
            log.warning(f"Team access denied: actor_team={cu_team_public_id} target_team={target_team_public_id}")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

        # Parse existing answers
        answers = target_user.answers or {}
        
        # Ensure the prompt exists in answers
        if request.prompt_key not in answers:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Prompt not found in user's answers"
            )
        
        # Get existing reactions
        if 'reactions' not in answers[request.prompt_key] or answers[request.prompt_key]['reactions'] is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No reactions found for this prompt"
            )
        
        reactions = answers[request.prompt_key]['reactions']
        # Extra safety check to ensure reactions is a list
        if reactions is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No reactions found for this prompt"
            )
        
        # Find and remove the specific reaction
        reaction_to_remove = next(
            (r for r in reactions if r.get('id') == request.reaction_id),
            None
        )
        
        if not reaction_to_remove:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Reaction not found"
            )
        
        # Check if the current user owns this reaction
        if reaction_to_remove.get('userId') != current_user.get('user_id'):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only remove your own reactions"
            )
        
        # Remove the reaction
        answers[request.prompt_key]['reactions'] = [
            r for r in reactions if r.get('id') != request.reaction_id
        ]
        
        # Update the user's answers
        target_user.answers = answers
        target_user.updated_at = datetime.now(timezone.utc)
        
        # Explicitly mark the answers field as modified for SQLAlchemy
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(target_user, 'answers')
        
        db.commit()
        db.refresh(target_user)
        
        return {
            "success": True,
            "message": "Reaction removed successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Exception in remove_reaction")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to remove reaction: {str(e)}"
        )

@router.get("/user/{user_id}")
async def get_user_reactions(
    user_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(require_roles("USER", "ADMIN"))
):
    """Get all reactions for a specific user's answers"""
    try:
        user = db.query(WelcomepageUser).filter(
            WelcomepageUser.public_id == user_id
        ).first()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        answers = user.answers or {}
        reactions_by_prompt = {}
        
        for prompt_key, answer_data in answers.items():
            if isinstance(answer_data, dict) and 'reactions' in answer_data:
                reactions_by_prompt[prompt_key] = answer_data['reactions']
        
        return {
            "success": True,
            "reactions": reactions_by_prompt
        }
        
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Exception in get_user_reactions")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get reactions: {str(e)}"
        )
