"""
API endpoints for team-building game question generation
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from typing import List

from database import get_db
from models.welcomepage_user import WelcomepageUser
from models.team import Team
from schemas.game import GenerateQuestionsRequest, GenerateQuestionsResponse, Question, WaveGifUrlsResponse
from schemas.welcomepage_user import WelcomepageUserDTO
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
    import time
    start_time = time.time()
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
        convert_start = time.time()
        members_dict = [member.model_dump() for member in members]
        convert_time = (time.time() - convert_start) * 1000
        log.info(f"Model to dict conversion took {convert_time:.2f}ms")
        
        # Generate questions using the service
        service_start = time.time()
        questions_dict = await GameService.generate_questions(members_dict)
        service_time = (time.time() - service_start) * 1000
        log.info(f"GameService.generate_questions took {service_time:.2f}ms")
        
        # Convert dictionaries to Pydantic models
        pydantic_start = time.time()
        questions = [Question(**q) for q in questions_dict]
        pydantic_time = (time.time() - pydantic_start) * 1000
        log.info(f"Dict to Pydantic conversion took {pydantic_time:.2f}ms")
        
        total_time = (time.time() - start_time) * 1000
        log.info(f"Generated {len(questions)} questions in {total_time:.2f}ms total")
        
        return GenerateQuestionsResponse(questions=questions)
        
    except ValueError as e:
        # Handle missing API key or other configuration errors
        log.error(f"Configuration error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Game question generation is not configured: {str(e)}"
        )
    except Exception as e:
        import traceback
        log.error(f"Error generating questions: {e}")
        log.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate game questions: {str(e)}"
        )


@router.get("/team/{team_public_id}/random-members", response_model=List[WelcomepageUserDTO])
async def get_random_members(
    team_public_id: str,
    limit: int = Query(15, ge=3, le=50, description="Number of random members to return"),
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("USER", "ADMIN"))
):
    """
    Get random eligible team members for game question generation.
    
    Returns N random published team members who have welcomepage content
    (selectedPrompts or bentoWidgets). Members are filtered for is_draft = False
    and ordered randomly.
    """
    import time
    start_time = time.time()
    log.info(f"Fetching {limit} random members for team {team_public_id}")
    
    # Resolve team_public_id to team_id
    team_query_start = time.time()
    team = db.query(Team).filter_by(public_id=team_public_id).first()
    team_query_time = (time.time() - team_query_start) * 1000
    log.info(f"Team lookup took {team_query_time:.2f}ms")
    
    if not team:
        log.warning(f"Team not found: {team_public_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found"
        )
    
    # Verify user has access to this team
    user_team_id = current_user.get('team_id')
    if user_team_id and user_team_id != team.public_id:
        # Check if user is admin (admins can access any team)
        user_role = current_user.get('role')
        if user_role != 'ADMIN':
            log.warning(f"User {current_user.get('public_id')} attempted to access team {team_public_id}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this team"
            )
    
    try:
        # Query for eligible random members
        db_query_start = time.time()
        eligible = db.query(WelcomepageUser)\
            .filter(WelcomepageUser.team_id == team.id)\
            .filter(WelcomepageUser.is_draft == False)\
            .filter(
                or_(
                    WelcomepageUser.selected_prompts.isnot(None),
                    WelcomepageUser.bento_widgets.isnot(None)
                )
            )\
            .order_by(func.random())\
            .limit(limit)\
            .all()
        db_query_time = (time.time() - db_query_start) * 1000
        log.info(f"Database query took {db_query_time:.2f}ms, found {len(eligible)} eligible members")
        
        if not eligible:
            log.warning(f"No eligible members found for team {team_public_id}")
            return []
        
        # Convert to DTOs
        dto_start = time.time()
        members = [WelcomepageUserDTO.model_validate(user) for user in eligible]
        dto_time = (time.time() - dto_start) * 1000
        log.info(f"DTO conversion took {dto_time:.2f}ms")
        
        total_time = (time.time() - start_time) * 1000
        log.info(f"Total get_random_members time: {total_time:.2f}ms")
        
        return members
        
    except Exception as e:
        log.error(f"Error fetching random members: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch random members"
        )


@router.get("/team/{team_public_id}/wave-gif-urls", response_model=WaveGifUrlsResponse)
async def get_wave_gif_urls(
    team_public_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("USER", "ADMIN"))
):
    """
    Get random wave GIF URLs for decorative animations.
    
    Returns up to 30 random wave GIF URLs from published team members.
    If the team has fewer than 30 members with wave GIFs, returns all available.
    This represents the broader team, not just members selected for questions.
    """
    import time
    start_time = time.time()
    log.info(f"Fetching wave GIF URLs for team {team_public_id}")
    
    # Resolve team_public_id to team_id
    team_query_start = time.time()
    team = db.query(Team).filter_by(public_id=team_public_id).first()
    team_query_time = (time.time() - team_query_start) * 1000
    log.info(f"Team lookup took {team_query_time:.2f}ms")
    
    if not team:
        log.warning(f"Team not found: {team_public_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found"
        )
    
    # Verify user has access to this team
    user_team_id = current_user.get('team_id')
    if user_team_id and user_team_id != team.public_id:
        # Check if user is admin (admins can access any team)
        user_role = current_user.get('role')
        if user_role != 'ADMIN':
            log.warning(f"User {current_user.get('public_id')} attempted to access team {team_public_id}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this team"
            )
    
    try:
        # Query for published members with wave_gif_url
        # Only need the wave_gif_url field, so we can optimize the query
        db_query_start = time.time()
        eligible = db.query(WelcomepageUser.wave_gif_url)\
            .filter(WelcomepageUser.team_id == team.id)\
            .filter(WelcomepageUser.is_draft == False)\
            .filter(WelcomepageUser.wave_gif_url.isnot(None))\
            .filter(WelcomepageUser.wave_gif_url != '')\
            .order_by(func.random())\
            .limit(30)\
            .all()
        db_query_time = (time.time() - db_query_start) * 1000
        log.info(f"Database query took {db_query_time:.2f}ms, found {len(eligible)} members with wave GIFs")
        
        # Extract URLs from query results (they come as tuples)
        urls = [url[0] for url in eligible if url[0]]
        
        total_time = (time.time() - start_time) * 1000
        log.info(f"Total get_wave_gif_urls time: {total_time:.2f}ms, returning {len(urls)} URLs")
        
        return WaveGifUrlsResponse(urls=urls)
        
    except Exception as e:
        log.error(f"Error fetching wave GIF URLs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch wave GIF URLs"
        )

