"""
API endpoints for team-building game question generation
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from database import get_db
from schemas.game import GenerateQuestionsRequest, GenerateQuestionsResponse, Question
from services.game_service import GameService
from utils.logger_factory import new_logger
from utils.jwt_auth import require_roles

router = APIRouter()
log = new_logger("game_api")


@router.post("/team/game/generate-questions", response_model=GenerateQuestionsResponse)
async def generate_questions(
    request: GenerateQuestionsRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("USER", "ADMIN"))
):
    """
    Generate game questions from team members' welcomepage content.
    
    Requires at least 3 team members with welcomepage content.
    Returns a mix of 'guess-who' and 'two-truths-lie' questions.
    """
    log.info(f"Generating game questions for user {current_user.get('public_id')}, team {current_user.get('team_id')}")
    
    members = request.members
    log.info(f"Received request with {len(members)} members")
    
    # Validate input
    if not members or len(members) < 3:
        log.warning(f"Invalid request: {len(members) if members else 0} members provided (need at least 3)")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least 3 team members required"
        )
    
    try:
        # Convert Pydantic models to dictionaries for service layer
        members_dict = [member.model_dump() for member in members]
        
        # Generate questions using the service
        questions_dict = await GameService.generate_questions(members_dict)
        
        # Convert dictionaries to Pydantic models
        questions = [Question(**q) for q in questions_dict]
        
        log.info(f"Generated {len(questions)} questions")
        
        return GenerateQuestionsResponse(questions=questions)
        
    except ValueError as e:
        # Handle missing API key or other configuration errors
        log.error(f"Configuration error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Game question generation is not configured: {str(e)}"
        )
    except Exception as e:
        log.error(f"Error generating questions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate game questions"
        )

