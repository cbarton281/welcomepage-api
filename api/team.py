import httpx
import os
import json
import logging
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
from sqlalchemy import desc, asc, func
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log
from pydantic import BaseModel

from database import get_db
from models.team import Team
from models.welcomepage_user import WelcomepageUser
from models.page_visit import PageVisit
from schemas.team import TeamCreate, TeamRead
from utils.logger_factory import new_logger
from utils.jwt_auth import require_roles
from utils.supabase_storage import upload_to_supabase_storage

router = APIRouter()

team_retry_logger = new_logger("fetch_team_by_public_id_retry")

# Pydantic models for team members response
class TeamMemberResponse(BaseModel):
    id: int
    public_id: str
    first_name: str
    last_name: str
    email: Optional[str]
    profile_image: Optional[str]
    date_created: str
    last_modified: str
    unique_visits: int
    auth_role: Optional[str]
    is_draft: bool

class TeamMembersListResponse(BaseModel):
    members: List[TeamMemberResponse]
    total_count: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_previous: bool

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(OperationalError),
    before_sleep=before_sleep_log(team_retry_logger, logging.WARNING)
)
def fetch_team_by_public_id(db: Session, public_id: str):
    try:
        return db.query(Team).filter_by(public_id=public_id).first()
    except OperationalError:
        db.rollback()
        raise

@router.get("/teams/{public_id}", response_model=TeamRead)
async def get_team(public_id: str, db: Session = Depends(get_db), current_user=Depends(require_roles("USER", "ADMIN", "PRE_SIGNUP"))):
    log = new_logger("get_team")
    log.info(f"Fetching team with public_id: {public_id}")
    team = fetch_team_by_public_id(db, public_id)
    if not team:
        log.warning(f"Team not found: {public_id}")
        raise HTTPException(status_code=404, detail="Team not found")
    else:
        log.info(f"Team found [{team.to_dict()}]")
    return TeamRead.model_validate(team)

@router.get("/teams/{public_id}/members", response_model=TeamMembersListResponse)
async def get_team_members(
    public_id: str,
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(20, ge=1, le=100, description="Number of members per page"),
    sort_by: str = Query("date_created", description="Sort field: date_created, last_modified, name, email"),
    sort_order: str = Query("desc", description="Sort order: asc or desc"),
    search: Optional[str] = Query(None, description="Search by name or email"),
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("ADMIN"))
):
    """
    Get paginated list of team members for a specific team.
    Supports filtering, searching, and sorting.
    """
    log = new_logger("get_team_members")
    log.info(f"Fetching team members for team: {public_id}, page: {page}, page_size: {page_size}")
    
    log.info(f"Current user: {current_user}")

    
    # First verify the team exists
    team = fetch_team_by_public_id(db, public_id)
    if not team:
        log.warning(f"Team not found: {public_id}")
        raise HTTPException(status_code=404, detail="Team not found")
    
    # Verify current user belongs to this team (for security)
    current_user_id = current_user.get('public_id') if isinstance(current_user, dict) else None
    current_user_team_id = current_user.get('team_id') if isinstance(current_user, dict) else None
    
    log.info(f"Current user team ID: {current_user_team_id}")
    log.info(f"Team ID: {team.public_id}")

    if current_user_team_id != team.public_id:
        log.warning(f"User {current_user_id} attempted to access team {public_id} members")
        raise HTTPException(status_code=403, detail="Access denied: You can only view members of your own team")
    
    # Build base query - only include registered users (with auth_email and USER/ADMIN roles)
    query = db.query(WelcomepageUser).filter(
        WelcomepageUser.team_id == team.id,
        WelcomepageUser.auth_email.isnot(None),
        WelcomepageUser.auth_email != '',
        WelcomepageUser.auth_role.in_(['USER', 'ADMIN'])
    )
    
    # Apply search filter if provided
    if search:
        search_term = f"%{search.lower()}%"
        query = query.filter(
            (WelcomepageUser.name.ilike(search_term)) |
            (WelcomepageUser.auth_email.ilike(search_term))
        )
    
    # Apply sorting
    sort_column = None
    if sort_by == "date_created":
        sort_column = WelcomepageUser.created_at
    elif sort_by == "last_modified":
        sort_column = WelcomepageUser.updated_at
    elif sort_by == "name":
        sort_column = WelcomepageUser.name
    elif sort_by == "email":
        sort_column = WelcomepageUser.auth_email
    else:
        sort_column = WelcomepageUser.created_at  # default
    
    if sort_order.lower() == "asc":
        query = query.order_by(asc(sort_column))
    else:
        query = query.order_by(desc(sort_column))
    
    # Get total count before pagination
    total_count = query.count()
    
    # Apply pagination
    offset = (page - 1) * page_size
    members = query.offset(offset).limit(page_size).all()
    
    # Calculate pagination metadata
    total_pages = (total_count + page_size - 1) // page_size  # Ceiling division
    has_next = page < total_pages
    has_previous = page > 1
    
    # Get visit counts for all team members in a single efficient query
    member_ids = [member.id for member in members]
    visit_counts = {}
    
    if member_ids:
        # Query to get unique visit counts for all members (all visitors are authenticated)
        visit_stats = db.query(
            PageVisit.visited_user_id,
            func.count(func.distinct(PageVisit.visitor_public_id)).label('unique_visits')
        ).filter(
            PageVisit.visited_user_id.in_(member_ids)
        ).group_by(PageVisit.visited_user_id).all()
        
        # Create a lookup dictionary for visit counts
        visit_counts = {stat.visited_user_id: stat.unique_visits for stat in visit_stats}
        log.info(f"Retrieved visit counts for {len(visit_counts)} members")
    
    # Transform data to match frontend expectations
    member_responses = []
    for member in members:
        # Parse name into first/last name (simple split on first space)
        name_parts = member.name.split(' ', 1) if member.name else ['', '']
        first_name = name_parts[0] if len(name_parts) > 0 else ''
        last_name = name_parts[1] if len(name_parts) > 1 else ''
        
        # Get real unique visit count from database
        unique_visits = visit_counts.get(member.id, 0)
        
        member_responses.append(TeamMemberResponse(
            id=member.id,
            public_id=member.public_id,
            first_name=first_name,
            last_name=last_name,
            email=member.auth_email,
            profile_image=member.profile_photo_url,
            date_created=member.created_at.isoformat() if member.created_at else datetime.now().isoformat(),
            last_modified=member.updated_at.isoformat() if member.updated_at else datetime.now().isoformat(),
            unique_visits=unique_visits,
            auth_role=member.auth_role,
            is_draft=member.is_draft
        ))
    
    log.info(f"Returning {len(member_responses)} members out of {total_count} total")
    
    return TeamMembersListResponse(
        members=member_responses,
        total_count=total_count,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        has_next=has_next,
        has_previous=has_previous
    )

@router.delete("/teams/{public_id}/members/{member_public_id}")
async def delete_team_member(
    public_id: str,
    member_public_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("ADMIN"))
):
    """
    Delete a team member from the team.
    Only ADMIN users can delete team members.
    """
    log = new_logger("delete_team_member")
    log.info(f"Deleting team member {member_public_id} from team {public_id}")
    
    # First verify the team exists
    team = fetch_team_by_public_id(db, public_id)
    if not team:
        log.warning(f"Team not found: {public_id}")
        raise HTTPException(status_code=404, detail="Team not found")
    
    # Verify current user belongs to this team (for security)
    current_user_id = current_user.get('user_id') if isinstance(current_user, dict) else None
    current_user_team_id = current_user.get('team_id') if isinstance(current_user, dict) else None
    
    # Clean up team_id if it has extra path components
    if current_user_team_id and '/' in current_user_team_id:
        current_user_team_id = current_user_team_id.split('/')[0]
    
    if current_user_team_id != team.public_id:
        log.warning(f"User {current_user_id} attempted to delete member from team {public_id}")
        raise HTTPException(status_code=403, detail="Access denied: You can only delete members from your own team")
    
    # Find the member to delete
    member_to_delete = db.query(WelcomepageUser).filter(
        WelcomepageUser.public_id == member_public_id,
        WelcomepageUser.team_id == team.id
    ).first()
    
    if not member_to_delete:
        log.warning(f"Member not found: {member_public_id} in team {public_id}")
        raise HTTPException(status_code=404, detail="Team member not found")
    
    # Prevent self-deletion
    if member_to_delete.public_id == current_user_id:
        log.warning(f"User {current_user_id} attempted to delete themselves")
        raise HTTPException(status_code=400, detail="You cannot delete yourself")
    
    try:
        # Delete the member
        db.delete(member_to_delete)
        db.commit()
        
        log.info(f"Successfully deleted member {member_public_id} from team {public_id}")
        
        return {
            "success": True,
            "message": f"Team member {member_to_delete.name} has been deleted successfully",
            "deleted_member_id": member_public_id
        }
        
    except Exception as e:
        db.rollback()
        log.error(f"Failed to delete member {member_public_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to delete team member")

# Pydantic model for role change request
class ChangeRoleRequest(BaseModel):
    new_role: str

@router.patch("/teams/{public_id}/members/{member_public_id}/role")
async def change_team_member_role(
    public_id: str,
    member_public_id: str,
    request: ChangeRoleRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("ADMIN"))
):
    """
    Change a team member's role.
    Only ADMIN users can change team member roles.
    """
    log = new_logger("change_team_member_role")
    log.info(f"Changing role for member {member_public_id} in team {public_id} to {request.new_role}")
    
    # Validate the new role
    if request.new_role not in ["USER", "ADMIN"]:
        log.warning(f"Invalid role requested: {request.new_role}")
        raise HTTPException(status_code=400, detail="Invalid role. Must be USER or ADMIN")
    
    # First verify the team exists
    team = fetch_team_by_public_id(db, public_id)
    if not team:
        log.warning(f"Team not found: {public_id}")
        raise HTTPException(status_code=404, detail="Team not found")
    
    # Verify current user belongs to this team (for security)
    current_user_id = current_user.get('public_id') if isinstance(current_user, dict) else None
    current_user_team_id = current_user.get('team_id') if isinstance(current_user, dict) else None
    
    if current_user_team_id != team.public_id:
        log.warning(f"User {current_user_id} attempted to change role in team {public_id} but belongs to team {current_user_team_id}")
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Find the target member
    target_member = db.query(WelcomepageUser).filter_by(
        public_id=member_public_id,
        team_id=team.id
    ).first()
    
    if not target_member:
        log.warning(f"Member {member_public_id} not found in team {public_id}")
        raise HTTPException(status_code=404, detail="Team member not found")
    
    # Prevent users from changing their own role
    if current_user_id == member_public_id:
        log.warning(f"User {current_user_id} attempted to change their own role")
        raise HTTPException(status_code=400, detail="Cannot change your own role")
    
    try:
        # Update the member's role
        old_role = target_member.auth_role
        target_member.auth_role = request.new_role
        db.commit()
        
        log.info(f"Successfully changed role for member {member_public_id} from {old_role} to {request.new_role}")
        
        return {
            "success": True,
            "message": f"Role changed from {old_role} to {request.new_role}",
            "member_public_id": member_public_id,
            "old_role": old_role,
            "new_role": request.new_role
        }
        
    except Exception as e:
        db.rollback()
        log.error(f"Failed to change role for member {member_public_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to change team member role")

from fastapi.concurrency import run_in_threadpool

team_upsert_retry_logger = new_logger("upsert_team_retry")

@router.post("/teams/", response_model=TeamRead)
async def upsert_team(
    organization_name: str = Form(...),
    color_scheme: str = Form(...),
    color_scheme_data: Optional[str] = Form(None),
    slack_settings: Optional[str] = Form(None),
    company_logo: Optional[UploadFile] = File(None),
    public_id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("ADMIN", "PRE_SIGNUP"))
):
    log = new_logger("upsert_team")
    logo_blob_url = None
    if company_logo:
        content = await company_logo.read()
        logo_blob_url = await upload_to_supabase_storage(
            file_content=content,
            filename=f"{public_id or organization_name}-company-logo",
            content_type=company_logo.content_type or "image/png"
        )
    user_role = current_user.get('role') if isinstance(current_user, dict) else None
    team = await run_in_threadpool(
        upsert_team_db_logic,
        organization_name, color_scheme, color_scheme_data, slack_settings, logo_blob_url, public_id, db, log, user_role
    )
    return TeamRead.model_validate(team)

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log
from sqlalchemy.exc import OperationalError

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(OperationalError),
    before_sleep=before_sleep_log(team_upsert_retry_logger, logging.WARNING)
)
def upsert_team_db_logic(
    organization_name, color_scheme, color_scheme_data, slack_settings, logo_blob_url, public_id, db, log, user_role
):
    log.info(f"endpoint invoked [{organization_name}] [{public_id}] ")    
    # Upsert team record (update if exists, else create)
    team = None
    team_lookup_id = None
    if public_id:
        team = fetch_team_by_public_id(db, public_id)
        if not team:
            team_lookup_id = public_id
    if not team:
        from utils.short_id import generate_short_id_with_collision_check
        generated_short_id = generate_short_id_with_collision_check(db, Team, "team")

    effective_public_id = team.public_id if team else (team_lookup_id if team_lookup_id else generated_short_id)

    # --- PRE_SIGNUP logic enforcement ---
    if user_role == 'PRE_SIGNUP':
        if team and not team.is_draft:
            log.warning(f"PRE_SIGNUP user attempted to update finalized team [{effective_public_id}]")
            raise HTTPException(status_code=403, detail="Drafts can only be updated until finalized.")
        # Otherwise, allow create or update (if is_draft)

    # All file upload and await logic must be in the async upsert_team handler, not here.
    # Only DB upsert logic remains here.
    
    # Parse color scheme data
    color_scheme_obj = None
    if color_scheme_data:
        try:
            color_scheme_obj = json.loads(color_scheme_data)
            log.info(f"color scheme data: {color_scheme_obj}")
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON in color_scheme_data")
    
    # Parse slack settings data
    slack_settings_obj = None
    if slack_settings:
        try:
            slack_settings_obj = json.loads(slack_settings)
            log.info(f"slack settings data: {slack_settings_obj}")
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON in slack_settings")
    try:
        if team:
            log.info("Team exists, updating...")
            team.organization_name = organization_name
            team.color_scheme = color_scheme
            team.company_logo_url = logo_blob_url
            team.color_scheme_data = color_scheme_obj
            team.slack_settings = slack_settings_obj
        else:
            log.info("Creating new team...")
            team = Team(
                public_id=effective_public_id,
                organization_name=organization_name,
                color_scheme=color_scheme,
                color_scheme_data=color_scheme_obj,
                slack_settings=slack_settings_obj,
                company_logo_url=logo_blob_url,
            )
            db.add(team)
        db.commit()
        db.refresh(team)
        log.info(f"Upserted team: {team.to_dict()}")
        return team
    except OperationalError as e:
        db.rollback()
        log.exception("OperationalError in verify_code_with_retry, will retry.")
        raise  # trigger the retry
    except Exception as e:
        db.rollback()
        log.error(f"DB error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to upsert team")


# Team invitation endpoints
class TeamInfoResponse(BaseModel):
    public_id: str
    organization_name: str
    logo_url: Optional[str]
    member_count: int


@router.get("/teams/{public_id}/info", response_model=TeamInfoResponse)
async def get_team_info(public_id: str, db: Session = Depends(get_db)):
    """
    Get basic team information for invitation purposes.
    This endpoint is public and doesn't require authentication.
    """
    log = new_logger("get_team_info")
    log.info(f"Fetching team info for invitation: {public_id}")
    
    team = fetch_team_by_public_id(db, public_id)
    if not team:
        log.warning(f"Team not found for invitation: {public_id}")
        raise HTTPException(status_code=404, detail="Team not found")
    
    # Count team members (only registered users)
    member_count = db.query(WelcomepageUser).filter(
        WelcomepageUser.team_id == team.id,
        WelcomepageUser.auth_email.isnot(None),
        WelcomepageUser.auth_email != '',
        WelcomepageUser.auth_role.in_(['USER', 'ADMIN'])
    ).count()
    
    team_info = TeamInfoResponse(
        public_id=team.public_id,
        organization_name=team.organization_name,
        logo_url=team.company_logo_url,
        member_count=member_count
    )
    
    log.info(f"Team info retrieved: {team_info.dict()}")
    return team_info


class JoinTeamResponse(BaseModel):
    success: bool
    message: str
    team_public_id: str
    user_public_id: str


@router.post("/teams/{public_id}/join", response_model=JoinTeamResponse)
async def join_team(
    public_id: str, 
    db: Session = Depends(get_db), 
    current_user=Depends(require_roles("USER", "ADMIN"))
):
    """
    Allow an authenticated user to join a team via invitation.
    Only authenticated users (USER or ADMIN) can join teams.
    """
    log = new_logger("join_team")
    log.info(f"User attempting to join team: {public_id}")
    
    # Get current user info
    user_public_id = current_user.get('public_id') if isinstance(current_user, dict) else None
    user_role = current_user.get('role') if isinstance(current_user, dict) else None
    
    if not user_public_id:
        log.error("No user public_id found in current_user")
        raise HTTPException(status_code=401, detail="User authentication required")
    
    log.info(f"User {user_public_id} (role: {user_role}) attempting to join team {public_id}")
    
    # Verify target team exists
    target_team = fetch_team_by_public_id(db, public_id)
    if not target_team:
        log.warning(f"Target team not found: {public_id}")
        raise HTTPException(status_code=404, detail="Team not found")
    
    # Get the user from database
    user = db.query(WelcomepageUser).filter_by(public_id=user_public_id).first()
    if not user:
        log.error(f"User not found in database: {user_public_id}")
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check if user is already in the target team
    if user.team_id == target_team.id:
        log.info(f"User {user_public_id} is already a member of team {public_id}")
        return JoinTeamResponse(
            success=True,
            message="You are already a member of this team",
            team_public_id=target_team.public_id,
            user_public_id=user_public_id
        )
    
    try:
        # Update user's team membership
        old_team_id = user.team_id
        user.team_id = target_team.id
        user.auth_role = 'USER'  # New team members start as USER role
        
        db.commit()
        db.refresh(user)
        
        log.info(f"User {user_public_id} successfully joined team {public_id} (moved from team_id {old_team_id} to {target_team.id})")
        
        return JoinTeamResponse(
            success=True,
            message=f"Successfully joined {target_team.organization_name}",
            team_public_id=target_team.public_id,
            user_public_id=user_public_id
        )
        
    except Exception as e:
        db.rollback()
        log.error(f"Failed to join team: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to join team")