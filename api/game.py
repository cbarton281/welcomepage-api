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
from schemas.game import GenerateQuestionsRequest, GenerateQuestionsResponse, Question, WaveGifUrlsResponse, AlternatePoolResponse, AlternateMember, EligibleCountResponse, EstimateTimeResponse, GenerateSingleQuestionRequest, GenerateSingleQuestionResponse
from schemas.welcomepage_user import WelcomepageUserDTO
from services.game_service import GameService, DEFAULT_EXPECTED_OUTPUT_TOKENS
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
        
        # Convert alternate pool if provided
        alternate_pool_dict = None
        log.info(f"Request alternatePool provided: {request.alternatePool is not None}, length: {len(request.alternatePool) if request.alternatePool else 0}")
        if request.alternatePool and len(request.alternatePool) > 0:
            alternate_pool_dict = [alt.model_dump() for alt in request.alternatePool]
            log.info(f"Using alternate pool with {len(alternate_pool_dict)} members for distractors")
            log.info(f"Alternate pool IDs: {[alt.get('public_id') for alt in alternate_pool_dict[:5]]}... (showing first 5)")
        else:
            if request.alternatePool is not None and len(request.alternatePool) == 0:
                log.info("Alternate pool provided but empty - will fall back to members list for distractors")
            else:
                log.warning("No alternatePool provided in request - distractors will fall back to members list")
        
        # Generate questions using the service
        service_start = time.time()
        questions_dict = await GameService.generate_questions(members_dict, alternate_pool_dict)
        service_time = (time.time() - service_start) * 1000
        log.info(f"GameService.generate_questions took {service_time:.2f}ms")
        
        # Convert dictionaries to Pydantic models
        pydantic_start = time.time()
        questions = [Question(**q) for q in questions_dict]
        pydantic_time = (time.time() - pydantic_start) * 1000
        log.info(f"Dict to Pydantic conversion took {pydantic_time:.2f}ms")
        
        # Calculate eligible count for the team
        eligible_count = None
        try:
            team_public_id = current_user.get('team_id')
            if team_public_id:
                count_start = time.time()
                team = db.query(Team).filter_by(public_id=team_public_id).first()
                if team:
                    eligible_count = db.query(WelcomepageUser)\
                        .filter(WelcomepageUser.team_id == team.id)\
                        .filter(WelcomepageUser.is_draft == False)\
                        .filter(
                            or_(
                                WelcomepageUser.selected_prompts.isnot(None),
                                WelcomepageUser.bento_widgets.isnot(None)
                            )
                        )\
                        .count()
                    count_time = (time.time() - count_start) * 1000
                    log.info(f"Eligible count query took {count_time:.2f}ms, found {eligible_count} eligible members")
        except Exception as e:
            log.warning(f"Failed to calculate eligible count: {e}")
            # Continue without eligible_count - it's optional
        
        total_time = (time.time() - start_time) * 1000
        log.info(f"Generated {len(questions)} questions in {total_time:.2f}ms total")
        
        return GenerateQuestionsResponse(questions=questions, eligible_count=eligible_count)
        
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


@router.post("/team/game/estimate-time", response_model=EstimateTimeResponse)
async def estimate_generation_time(
    request: GenerateQuestionsRequest,
    current_user=Depends(require_roles("USER", "ADMIN"))
):
    """
    Estimate the time it will take to generate game questions.
    This is a lightweight endpoint that doesn't make OpenAI API calls.
    Returns an estimated duration in seconds based on token counting.
    """
    import uuid
    request_id = str(uuid.uuid4())[:8]
    log.info(f"[REQUEST_ID:{request_id}] Estimating generation time for user {current_user.get('public_id')}")
    
    members = request.members
    log.info(f"[REQUEST_ID:{request_id}] Received estimation request with {len(members)} members")
    
    # Validate input
    if not members or len(members) < 3:
        log.warning(f"[REQUEST_ID:{request_id}] Invalid request: {len(members) if members else 0} members provided (need at least 3)")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least 3 team members required"
        )
    
    try:
        # Convert Pydantic models to dictionaries for service layer
        members_dict = [member.model_dump() for member in members]
        
        # Get estimate (lightweight, no OpenAI call)
        estimated_seconds = GameService.estimate_generation_time(members_dict, request_id)
        
        # Get token estimates for additional info (optional)
        try:
            system_prompt, user_prompt = GameService._build_prompts_for_estimation(members_dict)
            combined_prompt = system_prompt + "\n\n" + user_prompt if system_prompt and user_prompt else ""
            prompt_tokens_est = GameService._count_tokens_for_model(combined_prompt, "gpt-4o") if combined_prompt else None
            from services.game_service import DEFAULT_EXPECTED_OUTPUT_TOKENS
            expected_output_tokens = min(DEFAULT_EXPECTED_OUTPUT_TOKENS, 1500)
        except Exception as e:
            log.warning(f"[REQUEST_ID:{request_id}] Failed to get detailed token estimates: {e}")
            prompt_tokens_est = None
            expected_output_tokens = None
        
        # Log the final estimate being returned
        log.info(
            f"[REQUEST_ID:{request_id}] Returning estimate: {estimated_seconds:.2f}s "
            f"(prompt_tokens={prompt_tokens_est}, expected_output_tokens={expected_output_tokens})"
        )
        
        return EstimateTimeResponse(
            estimated_seconds=estimated_seconds,
            prompt_tokens_estimate=prompt_tokens_est,
            expected_output_tokens=expected_output_tokens
        )
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        log.error(f"[REQUEST_ID:{request_id}] Error estimating generation time: {e}")
        log.error(f"[REQUEST_ID:{request_id}] Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to estimate generation time: {str(e)}"
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


@router.get("/team/{team_public_id}/game/alternate-pool", response_model=AlternatePoolResponse)
async def get_alternate_pool(
    team_public_id: str,
    exclude_subjects: str = Query(None, description="Comma-separated public_ids to exclude from the pool"),
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("USER", "ADMIN"))
):
    """
    Get alternate pool members for game distractors and animations.
    
    Returns up to 100 eligible team members with minimal data (public_id, name, wave_gif_url).
    If team has <= 100 eligible members, returns all. If > 100, returns 100 randomly selected.
    Excludes specified subject public_ids if provided.
    
    Used for:
    - Selecting distractors for game questions (excluding question subjects)
    - Extracting wave_gif_urls for landing page animations
    """
    import time
    start_time = time.time()
    log.info(f"Fetching alternate pool for team {team_public_id}, excluding subjects: {exclude_subjects}")
    
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
        # Parse exclude_subjects if provided
        exclude_ids = set()
        if exclude_subjects:
            exclude_ids = {pid.strip() for pid in exclude_subjects.split(',') if pid.strip()}
            log.info(f"Excluding {len(exclude_ids)} subject public_ids from alternate pool")
        
        # First, count total eligible members
        count_start = time.time()
        total_count = db.query(WelcomepageUser)\
            .filter(WelcomepageUser.team_id == team.id)\
            .filter(WelcomepageUser.is_draft == False)\
            .filter(
                or_(
                    WelcomepageUser.selected_prompts.isnot(None),
                    WelcomepageUser.bento_widgets.isnot(None)
                )
            )\
            .count()
        count_time = (time.time() - count_start) * 1000
        log.info(f"Count query took {count_time:.2f}ms, found {total_count} total eligible members")
        
        # Determine limit: if <= 100, fetch all; if > 100, fetch 100 random
        limit = total_count if total_count <= 100 else 100
        
        # Query for eligible members (excluding subjects if provided)
        db_query_start = time.time()
        query = db.query(WelcomepageUser)\
            .filter(WelcomepageUser.team_id == team.id)\
            .filter(WelcomepageUser.is_draft == False)\
            .filter(
                or_(
                    WelcomepageUser.selected_prompts.isnot(None),
                    WelcomepageUser.bento_widgets.isnot(None)
                )
            )
        
        # Exclude subjects if provided
        if exclude_ids:
            query = query.filter(~WelcomepageUser.public_id.in_(exclude_ids))
        
        # Order randomly and limit
        eligible = query.order_by(func.random()).limit(limit).all()
        db_query_time = (time.time() - db_query_start) * 1000
        log.info(f"Database query took {db_query_time:.2f}ms, found {len(eligible)} eligible members for alternate pool")
        
        # Convert to minimal AlternateMember objects
        convert_start = time.time()
        alternate_members = [
            AlternateMember(
                public_id=user.public_id,
                name=user.name,
                wave_gif_url=user.wave_gif_url
            )
            for user in eligible
        ]
        convert_time = (time.time() - convert_start) * 1000
        log.info(f"Conversion to AlternateMember took {convert_time:.2f}ms")
        
        total_time = (time.time() - start_time) * 1000
        log.info(f"Total get_alternate_pool time: {total_time:.2f}ms, returning {len(alternate_members)} members")
        
        return AlternatePoolResponse(members=alternate_members)
        
    except Exception as e:
        log.error(f"Error fetching alternate pool: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch alternate pool"
        )


@router.post("/team/game/generate-single-question", response_model=GenerateSingleQuestionResponse)
async def generate_single_question(
    request: GenerateSingleQuestionRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("USER", "ADMIN"))
):
    """
    Generate a single game question, excluding already-used subjects.
    
    This endpoint is optimized for adding or regenerating individual questions.
    It generates only 1 question instead of 10, making it faster and more efficient.
    
    Requires at least 1 team member with welcomepage content (after exclusions).
    """
    import time
    start_time = time.time()
    log.info(f"Generating single question for user {current_user.get('public_id')}, team {current_user.get('team_id')}")
    
    members = request.members
    exclude_subjects = request.excludeSubjects or []
    question_type = request.questionType
    
    log.info(f"Received request with {len(members)} members, excluding {len(exclude_subjects)} subjects")
    if exclude_subjects:
        log.info(f"Excluded subject IDs: {exclude_subjects[:5]}... (showing first 5)")
    
    # Validate input
    if not members or len(members) < 1:
        log.warning(f"Invalid request: {len(members) if members else 0} members provided (need at least 1)")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least 1 team member required"
        )
    
    try:
        # Convert Pydantic models to dictionaries for service layer
        members_dict = [member.model_dump() for member in members]
        
        # Convert alternate pool if provided
        alternate_pool_dict = None
        if request.alternatePool and len(request.alternatePool) > 0:
            alternate_pool_dict = [alt.model_dump() for alt in request.alternatePool]
            log.info(f"Using alternate pool with {len(alternate_pool_dict)} members for distractors")
        
        # Generate single question using the service
        service_start = time.time()
        question_dict = await GameService.generate_single_question(
            members_dict,
            exclude_subjects=exclude_subjects,
            question_type=question_type,
            alternate_pool=alternate_pool_dict
        )
        service_time = (time.time() - service_start) * 1000
        log.info(f"GameService.generate_single_question took {service_time:.2f}ms")
        
        # Convert dictionary to Pydantic model
        question = None
        if question_dict:
            question = Question(**question_dict)
        
        # Calculate eligible count for the team
        eligible_count = None
        try:
            team_public_id = current_user.get('team_id')
            if team_public_id:
                team = db.query(Team).filter_by(public_id=team_public_id).first()
                if team:
                    eligible_count = db.query(WelcomepageUser)\
                        .filter(WelcomepageUser.team_id == team.id)\
                        .filter(WelcomepageUser.is_draft == False)\
                        .filter(
                            or_(
                                WelcomepageUser.selected_prompts.isnot(None),
                                WelcomepageUser.bento_widgets.isnot(None)
                            )
                        )\
                        .count()
                    log.info(f"Eligible count query found {eligible_count} eligible members")
        except Exception as e:
            log.warning(f"Failed to calculate eligible count: {e}")
            # Continue without eligible_count - it's optional
        
        total_time = (time.time() - start_time) * 1000
        log.info(f"Generated single question in {total_time:.2f}ms total")
        
        return GenerateSingleQuestionResponse(question=question, eligible_count=eligible_count)
        
    except ValueError as e:
        # Handle missing API key or other configuration errors
        log.error(f"Configuration error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Game question generation is not configured: {str(e)}"
        )
    except Exception as e:
        import traceback
        log.error(f"Error generating single question: {e}")
        log.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate question: {str(e)}"
        )


@router.get("/team/{team_public_id}/game/eligible-count", response_model=EligibleCountResponse)
async def get_eligible_count(
    team_public_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("USER", "ADMIN"))
):
    """
    Get the total count of eligible team members for game question generation.
    
    Returns the count of published team members who have welcomepage content
    (selectedPrompts or bentoWidgets). This matches the eligibility logic used
    by the game service for question generation.
    """
    import time
    start_time = time.time()
    log.info(f"Fetching eligible member count for team {team_public_id}")
    
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
        # Count eligible members (same logic as get_random_members and game service)
        # Published (is_draft=False) AND has content (selectedPrompts or bentoWidgets)
        db_query_start = time.time()
        eligible_count = db.query(WelcomepageUser)\
            .filter(WelcomepageUser.team_id == team.id)\
            .filter(WelcomepageUser.is_draft == False)\
            .filter(
                or_(
                    WelcomepageUser.selected_prompts.isnot(None),
                    WelcomepageUser.bento_widgets.isnot(None)
                )
            )\
            .count()
        db_query_time = (time.time() - db_query_start) * 1000
        log.info(f"Database query took {db_query_time:.2f}ms, found {eligible_count} eligible members")
        
        total_time = (time.time() - start_time) * 1000
        log.info(f"Total get_eligible_count time: {total_time:.2f}ms")
        
        return EligibleCountResponse(eligible_count=eligible_count)
        
    except Exception as e:
        log.error(f"Error fetching eligible count: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch eligible count"
        )

