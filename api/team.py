import httpx
import os
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, Union
from fastapi import APIRouter, Depends, HTTPException, status, Query, Form, UploadFile, File
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, asc, desc, and_, or_, text
from sqlalchemy.exc import OperationalError, IntegrityError, DataError, DatabaseError
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log

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
    
    # Calculate published count for this team
    published_count = db.query(WelcomepageUser).filter(
        WelcomepageUser.team_id == team.id,
        WelcomepageUser.is_draft == False
    ).count()
    
    log.info(f"Team {public_id} has {published_count} published pages")
    
    # Create team response with published count
    team_response = TeamRead.model_validate(team)
    team_response.published_count = published_count
    
    return team_response

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

class TeamMemberViewResponse(BaseModel):
    id: int
    public_id: str
    name: Optional[str] = None
    first_name: str
    last_name: str
    role: Optional[str] = None
    nickname: Optional[str] = None
    pronunciation_text: Optional[str] = None
    pronunciation_recording_url: Optional[str] = None
    profile_image: Optional[str]
    wave_gif_url: Optional[str]
    unique_visits: int

class TeamMembersViewListResponse(BaseModel):
    members: List[TeamMemberViewResponse]
    total_count: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_previous: bool

@router.get("/teams/{public_id}/members-view", response_model=TeamMembersViewListResponse)
async def get_team_members_view(
    public_id: str,
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(20, ge=1, le=100, description="Number of members per page"),
    sort_by: str = Query("name", description="Sort field: name, date_created"),
    sort_order: str = Query("asc", description="Sort order: asc or desc"),
    search: Optional[str] = Query(None, description="Search by name or email"),
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("USER", "ADMIN"))
):
    """
    Get paginated list of team members for viewing (USER role access).
    Returns minimal information needed for team member display.
    """
    log = new_logger("get_team_members_view")
    log.info(f"Fetching team members view for team: {public_id}, page: {page}, page_size: {page_size}")
    
    # First verify the team exists
    team = fetch_team_by_public_id(db, public_id)
    if not team:
        log.warning(f"Team not found: {public_id}")
        raise HTTPException(status_code=404, detail="Team not found")
    
    # Verify current user belongs to this team (for security)
    current_user_id = current_user.get('public_id') if isinstance(current_user, dict) else None
    current_user_team_id = current_user.get('team_id') if isinstance(current_user, dict) else None
    
    if current_user_team_id != team.public_id:
        log.warning(f"User {current_user_id} attempted to access team {public_id} members view")
        raise HTTPException(status_code=403, detail="Access denied: You can only view members of your own team")
    
    # Build base query - only include registered users (with auth_email and USER/ADMIN roles)
    query = db.query(WelcomepageUser).filter(
        WelcomepageUser.team_id == team.id,
        WelcomepageUser.auth_email.isnot(None),
        WelcomepageUser.auth_email != '',
        WelcomepageUser.auth_role.in_(['USER', 'ADMIN'])
    )
    
    # Log base query count before search
    base_count = query.count()
    log.info(f"Base query (team_id={team.id}, with auth filters) returned {base_count} users")
    
    # Apply full-text search filter if provided
    if search:
        log.info(f"Applying full-text search filter for term: '{search}'")
        # Use PostgreSQL full-text search with search_vector column
        # For prefix matching (partial words), we use to_tsquery with :* operator
        # For full words/phrases, we use plainto_tsquery
        # This handles both "toronto" (full word) and "tor" (prefix) searches
        search_terms = search.strip().split()
        if len(search_terms) == 1 and len(search.strip()) < 20:
            # Single short term - use prefix matching for better partial word support
            # Escape special characters and append :* for prefix match
            # Replace spaces, quotes, and other special chars that break to_tsquery
            search_query_str = """
                to_tsquery('english', 
                    regexp_replace(
                        regexp_replace(:search_term, '[^a-zA-Z0-9\\s]', '', 'g'),
                        '\\s+', ' & ', 'g'
                    ) || ':*'
                )
            """
            log.info(f"Using prefix search mode for term: '{search}'")
        else:
            # Multiple words or long term - use plainto_tsquery (handles phrases better)
            search_query_str = "plainto_tsquery('english', :search_term)"
            log.info(f"Using phrase search mode for term: '{search}'")
        
        search_filter = text(f"search_vector @@ ({search_query_str})").bindparams(search_term=search)
        query = query.filter(search_filter)
        
        # Log count after search filter
        search_count = query.count()
        log.info(f"After search filter '{search}', query returned {search_count} users")
        
        # Debug: Check if search_vector is NULL for any users in this team
        null_vector_count = db.query(WelcomepageUser).filter(
            WelcomepageUser.team_id == team.id,
            WelcomepageUser.search_vector.is_(None)
        ).count()
        if null_vector_count > 0:
            log.warning(f"Found {null_vector_count} users in team {team.id} with NULL search_vector")
        
        # Debug: Test search without other filters
        search_only_count = db.query(WelcomepageUser).filter(
            WelcomepageUser.team_id == team.id
        ).filter(search_filter).count()
        log.info(f"Search '{search}' on team_id={team.id} (without auth filters) returned {search_only_count} users")
        
        # Debug: Check users excluded by auth filters
        excluded_by_auth = db.query(WelcomepageUser).filter(
            WelcomepageUser.team_id == team.id,
            or_(
                WelcomepageUser.auth_email.is_(None),
                WelcomepageUser.auth_email == '',
                ~WelcomepageUser.auth_role.in_(['USER', 'ADMIN'])
            )
        ).filter(search_filter).count()
        if excluded_by_auth > 0:
            log.info(f"Search '{search}' matched {excluded_by_auth} users excluded by auth filters (no auth_email or wrong role)")
    else:
        log.info("No search term provided, returning all filtered users")
    
    # Apply sorting
    sort_column = None
    if sort_by == "name":
        sort_column = WelcomepageUser.name
    elif sort_by == "date_created":
        sort_column = WelcomepageUser.created_at
    else:
        sort_column = WelcomepageUser.name  # default
    
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
    
    # Build response objects with minimal data
    member_responses = []
    for member in members:
        # Extract first and last name from full name
        name_parts = member.name.split(' ', 1) if member.name else ['', '']
        first_name = name_parts[0] if name_parts else ''
        last_name = name_parts[1] if len(name_parts) > 1 else ''
        
        member_responses.append(TeamMemberViewResponse(
            id=member.id,
            public_id=member.public_id,
            name=member.name,
            first_name=first_name,
            last_name=last_name,
            role=member.role,
            nickname=member.nickname,
            pronunciation_text=member.pronunciation_text,
            pronunciation_recording_url=member.pronunciation_recording_url,
            profile_image=member.profile_photo_url,
            wave_gif_url=member.wave_gif_url,
            unique_visits=0  # Simplified - no visit counting for team view
        ))
    
    log.info(f"Returning {len(member_responses)} members view out of {total_count} total (page {page} of {total_pages})")
    if search:
        log.info(f"Search results for '{search}': {total_count} total matches, showing page {page}")
    
    return TeamMembersViewListResponse(
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
    organization_name: Optional[str] = Form(None),
    color_scheme: Optional[str] = Form(None),
    color_scheme_data: Optional[str] = Form(None),
    slack_settings: Optional[str] = Form(None),
    company_logo: Optional[UploadFile] = File(None),
    remove_logo: Optional[bool] = Form(False),
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
        organization_name, color_scheme, color_scheme_data, slack_settings, logo_blob_url, remove_logo, public_id, db, log, user_role
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
    organization_name, color_scheme, color_scheme_data, slack_settings, logo_blob_url, remove_logo, public_id, db, log, user_role
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
    
    # Parse slack_settings only if provided; do not merge with existing values
    slack_settings_obj = None
    if slack_settings is not None:
        try:
            slack_settings_obj = json.loads(slack_settings)
            log.info(f"Incoming slack settings data parsed")
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON in slack_settings")
    try:
        if team:
            log.info("Team exists, updating...")
            # Only update fields that are explicitly provided in the form
            if organization_name is not None:
                team.organization_name = organization_name
            if color_scheme is not None:
                team.color_scheme = color_scheme
            if logo_blob_url is not None:
                team.company_logo_url = logo_blob_url
            elif remove_logo:
                # Explicitly clear the existing logo if requested and no new logo uploaded
                team.company_logo_url = None
            if color_scheme_data is not None:
                team.color_scheme_data = color_scheme_obj
            if slack_settings is not None:
                team.slack_settings = slack_settings_obj
        else:
            log.info("Creating new team...")
            # Validate required fields for creation
            if not organization_name or not color_scheme:
                raise HTTPException(status_code=400, detail="organization_name and color_scheme are required for team creation")
            team = Team(
                public_id=effective_public_id,
                organization_name=organization_name,
                color_scheme=color_scheme,
                color_scheme_data=color_scheme_obj,
                slack_settings=slack_settings_obj,
                company_logo_url=logo_blob_url,
                subscription_status="free",  # Initialize new teams with free subscription
            )
            db.add(team)
        db.commit()
        db.refresh(team)
        log.info(f"Upserted team: {team.to_dict()}")
        return team
    except OperationalError:
        # These exceptions are handled by the @retry decorator - let them bubble up
        db.rollback()
        raise
    except Exception as e:
        # Only catch non-retryable exceptions here
        db.rollback()
        log.error(f"Non-retryable DB error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to upsert team")


# Team invitation endpoints
class TeamInfoResponse(BaseModel):
    public_id: str
    organization_name: str
    logo_url: Optional[str]
    member_count: int
    stripe_customer_id: Optional[str] = None
    published_count: int = 0
    subscription_status: Optional[str] = None


@router.get("/teams/{public_id}/info", response_model=TeamInfoResponse)
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(OperationalError),
    before_sleep=before_sleep_log(team_retry_logger, logging.WARNING)
)
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
    
    # Count published pages (non-draft users with auth_email)
    published_count = db.query(WelcomepageUser).filter(
        WelcomepageUser.team_id == team.id,
        WelcomepageUser.is_draft == False,
        WelcomepageUser.auth_email.isnot(None),
        WelcomepageUser.auth_email != ''
    ).count()
    
    team_info = TeamInfoResponse(
        public_id=team.public_id,
        organization_name=team.organization_name,
        logo_url=team.company_logo_url,
        member_count=member_count,
        stripe_customer_id=team.stripe_customer_id,
        published_count=published_count,
        subscription_status=team.subscription_status
    )
    
    log.info(f"Team info retrieved: {team_info.dict()}")
    return team_info


# Public minimal branding for previews
class TeamBrandingResponse(BaseModel):
    public_id: str
    organization_name: str
    logo_url: Optional[str]
    color_scheme: Optional[str]
    color_scheme_data: Optional[dict]

@router.get("/public/teams/{public_id}/branding", response_model=TeamBrandingResponse)
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(OperationalError),
    before_sleep=before_sleep_log(team_retry_logger, logging.WARNING)
)
async def get_team_branding(public_id: str, db: Session = Depends(get_db)):
    """
    Public endpoint to fetch minimal branding for preview purposes.
    Contains only non-sensitive fields: organization_name, logo_url, color scheme info.
    """
    log = new_logger("get_team_branding")
    log.info(f"Fetching public branding for team: {public_id}")
    team = fetch_team_by_public_id(db, public_id)
    if not team:
        log.warning(f"Team not found for branding: {public_id}")
        raise HTTPException(status_code=404, detail="Team not found")
    return TeamBrandingResponse(
        public_id=team.public_id,
        organization_name=team.organization_name,
        logo_url=team.company_logo_url,
        color_scheme=team.color_scheme,
        color_scheme_data=team.color_scheme_data or None,
    )


class JoinTeamResponse(BaseModel):
    success: bool
    message: str
    team_public_id: str
    user_public_id: str

class JoinTeamRequest(BaseModel):
    slack_user_id: Optional[str] = None
    slack_name: Optional[str] = None

class SlackChannelData(BaseModel):
    id: str
    name: Optional[str] = None
    team_id: Optional[str] = None

class UpdateSlackSettingsRequest(BaseModel):
    auto_invite_users: Optional[bool] = None
    publish_channel: Optional[SlackChannelData] = None

class UpdateSlackSettingsResponse(BaseModel):
    success: bool
    message: str
    auto_invite_users: Optional[bool] = None
    publish_channel: Optional[SlackChannelData] = None


# =====================
# Sharing Settings
# =====================

class UpdateSharingSettingsRequest(BaseModel):
    enabled: Optional[bool] = None
    expires_at: Optional[str] = None  # ISO 8601 datetime string or null

class SharingSettingsResponse(BaseModel):
    enabled: bool
    uuid: Optional[str] = None
    expires_at: Optional[str] = None  # ISO 8601 datetime string or null

class UpdateSharingSettingsResponse(BaseModel):
    success: bool
    message: str
    enabled: bool
    uuid: Optional[str] = None
    expires_at: Optional[str] = None


@router.post("/teams/{public_id}/join", response_model=JoinTeamResponse)
async def join_team(
    public_id: str, 
    request: Optional[JoinTeamRequest] = None,
    db: Session = Depends(get_db), 
    current_user=Depends(require_roles("USER", "ADMIN"))
):
    # Deprecated: Invitation user flow assigns users to teams directly; join is no longer required.
    return JSONResponse(
        {"detail": "This endpoint has been removed. The Slack join flow creates the invitation user directly and no longer requires a separate join call."},
        status_code=status.HTTP_410_GONE,
    )


@router.get("/teams/{public_id}/slack-settings")
async def get_slack_settings(
    public_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("ADMIN"))
):
    """
    Get Slack settings for a team.
    Only ADMIN users can access Slack settings.
    """
    log = new_logger("get_slack_settings")
    log.info(f"Getting Slack settings for team: {public_id}")
    
    # Get current user info
    user_public_id = current_user.get('public_id') if isinstance(current_user, dict) else None
    user_team_id = current_user.get('team_id') if isinstance(current_user, dict) else None
    
    if not user_public_id:
        log.error("No user public_id found in current_user")
        raise HTTPException(status_code=401, detail="User authentication required")
    
    # Verify target team exists
    team = fetch_team_by_public_id(db, public_id)
    if not team:
        log.warning(f"Team not found: {public_id}")
        raise HTTPException(status_code=404, detail="Team not found")
    
    # Verify current user belongs to this team (for security)
    if user_team_id != team.public_id:
        log.warning(f"User {user_public_id} attempted to access Slack settings for team {public_id} but belongs to team {user_team_id}")
        raise HTTPException(status_code=403, detail="Access denied: You can only access settings for your own team")
    
    # Return slack_settings or empty dict if none exist
    slack_settings = team.slack_settings or {}
    log.info(f"Retrieved Slack settings for team {public_id}: {slack_settings}")
    
    return slack_settings


@router.patch("/teams/{public_id}/slack-settings", response_model=UpdateSlackSettingsResponse)
async def update_slack_settings(
    public_id: str,
    request: UpdateSlackSettingsRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("ADMIN"))
):
    """
    Update Slack settings for a team.
    Only ADMIN users can update Slack settings.
    """
    log = new_logger("update_slack_settings")
    log.info(f"Updating Slack settings for team: {public_id}")
    
    # Get current user info
    user_public_id = current_user.get('public_id') if isinstance(current_user, dict) else None
    user_team_id = current_user.get('team_id') if isinstance(current_user, dict) else None
    
    if not user_public_id:
        log.error("No user public_id found in current_user")
        raise HTTPException(status_code=401, detail="User authentication required")
    
    # Verify target team exists
    team = fetch_team_by_public_id(db, public_id)
    if not team:
        log.warning(f"Team not found: {public_id}")
        raise HTTPException(status_code=404, detail="Team not found")
    
    # Verify current user belongs to this team (for security)
    if user_team_id != team.public_id:
        log.warning(f"User {user_public_id} attempted to update Slack settings for team {public_id} but belongs to team {user_team_id}")
        raise HTTPException(status_code=403, detail="Access denied: You can only update settings for your own team")
    
    try:
        # Validate that at least one field is provided
        if request.auto_invite_users is None and request.publish_channel is None:
            raise HTTPException(status_code=400, detail="At least one field must be provided")
        
        # Get existing slack_settings or initialize empty dict
        existing_settings = team.slack_settings or {}
        
        # Update the settings based on what was provided
        if request.auto_invite_users is not None:
            existing_settings["auto_invite_users"] = request.auto_invite_users
            
        if request.publish_channel is not None:
            # Convert SlackChannelData model to dict for JSON storage
            if request.publish_channel:
                existing_settings["publish_channel"] = {
                    "id": request.publish_channel.id,
                    "name": request.publish_channel.name
                }
        
        # Update the team's slack_settings
        team.slack_settings = dict(existing_settings)
        
        # Explicitly mark the field as modified for SQLAlchemy
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(team, 'slack_settings')
        
        db.commit()
        db.refresh(team)
        
        log.info(f"Updated Slack settings for team {public_id}: auto_invite_users = {request.auto_invite_users}, publish_channel = {request.publish_channel}")
        
        return UpdateSlackSettingsResponse(
            success=True,
            message="Slack settings updated successfully",
            auto_invite_users=existing_settings.get("auto_invite_users"),
            publish_channel=existing_settings.get("publish_channel")
        )
        
    except Exception as e:
        db.rollback()
        log.error(f"Failed to update Slack settings for team {public_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update Slack settings")


@router.get("/teams/{public_id}/sharing-settings", response_model=SharingSettingsResponse)
async def get_sharing_settings(
    public_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("ADMIN"))
):
    """
    Get sharing settings for a team.
    Only ADMIN users can access sharing settings.
    """
    log = new_logger("get_sharing_settings")
    log.info(f"Getting sharing settings for team: {public_id}")
    
    # Get current user info
    user_public_id = current_user.get('public_id') if isinstance(current_user, dict) else None
    user_team_id = current_user.get('team_id') if isinstance(current_user, dict) else None
    
    if not user_public_id:
        log.error("No user public_id found in current_user")
        raise HTTPException(status_code=401, detail="User authentication required")
    
    # Verify target team exists
    team = fetch_team_by_public_id(db, public_id)
    if not team:
        log.warning(f"Team not found: {public_id}")
        raise HTTPException(status_code=404, detail="Team not found")
    
    # Verify current user belongs to this team (for security)
    if user_team_id != team.public_id:
        log.warning(f"User {user_public_id} attempted to access sharing settings for team {public_id} but belongs to team {user_team_id}")
        raise HTTPException(status_code=403, detail="Access denied: You can only access settings for your own team")
    
    # Get existing sharing_settings or initialize with defaults
    sharing_settings = team.sharing_settings or {}
    
    # Return settings (uuid and expires_at will be None if sharing was disabled)
    return SharingSettingsResponse(
        enabled=sharing_settings.get("enabled", False),
        uuid=sharing_settings.get("uuid"),  # Will be None if disabled or uninitialized
        expires_at=sharing_settings.get("expires_at")  # Will be None if disabled or uninitialized
    )


@router.patch("/teams/{public_id}/sharing-settings", response_model=UpdateSharingSettingsResponse)
async def update_sharing_settings(
    public_id: str,
    request: UpdateSharingSettingsRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("ADMIN"))
):
    """
    Update sharing settings for a team.
    Only ADMIN users can update sharing settings.
    Generates UUID server-side when sharing is enabled for the first time.
    """
    log = new_logger("update_sharing_settings")
    log.info(f"Updating sharing settings for team: {public_id}")
    
    # Get current user info
    user_public_id = current_user.get('public_id') if isinstance(current_user, dict) else None
    user_team_id = current_user.get('team_id') if isinstance(current_user, dict) else None
    
    if not user_public_id:
        log.error("No user public_id found in current_user")
        raise HTTPException(status_code=401, detail="User authentication required")
    
    # Verify target team exists
    team = fetch_team_by_public_id(db, public_id)
    if not team:
        log.warning(f"Team not found: {public_id}")
        raise HTTPException(status_code=404, detail="Team not found")
    
    # Verify current user belongs to this team (for security)
    if user_team_id != team.public_id:
        log.warning(f"User {user_public_id} attempted to update sharing settings for team {public_id} but belongs to team {user_team_id}")
        raise HTTPException(status_code=403, detail="Access denied: You can only update settings for your own team")
    
    try:
        # Get existing sharing_settings or initialize empty dict
        existing_settings = team.sharing_settings or {}
        
        # Track if we just disabled sharing
        just_disabled = False
        
        # Update enabled status
        if request.enabled is not None:
            previous_enabled = existing_settings.get("enabled", False)
            existing_settings["enabled"] = request.enabled
            
            if request.enabled:
                # Generate UUID when enabling sharing (if not already present)
                if not existing_settings.get("uuid"):
                    from utils.short_id import generate_short_id
                    new_uuid = generate_short_id(25)
                    existing_settings["uuid"] = new_uuid
                    log.info(f"Generated new sharing UUID for team {public_id}: {new_uuid}")
            else:
                # When disabling sharing, clear uuid and expires_at
                if previous_enabled:  # Only clear if it was previously enabled
                    existing_settings.pop("uuid", None)
                    existing_settings.pop("expires_at", None)
                    just_disabled = True
                    log.info(f"Cleared UUID and expiry date for team {public_id} when disabling sharing")
        
        # Update expires_at only if sharing is enabled (skip if we just disabled it)
        # This prevents re-setting expires_at when disabling sharing
        # Note: We need to check if expires_at was provided in the request, even if it's None/null
        # to allow clearing the expiration date
        expires_at_provided = hasattr(request, 'expires_at') and 'expires_at' in request.model_dump(exclude_unset=True)
        
        if expires_at_provided and not just_disabled and existing_settings.get("enabled", False):
            if request.expires_at is None or request.expires_at == "" or request.expires_at.lower() == "null":
                # Explicitly clear the expiration date
                existing_settings["expires_at"] = None
                log.info(f"Cleared expiration date for team {public_id}")
            else:
                # Validate that the date is in the future
                try:
                    expires_datetime = datetime.fromisoformat(request.expires_at.replace('Z', '+00:00'))
                    if expires_datetime <= datetime.now(expires_datetime.tzinfo if expires_datetime.tzinfo else None):
                        raise HTTPException(status_code=400, detail="Expiration date must be in the future")
                    # Store as ISO string
                    existing_settings["expires_at"] = expires_datetime.isoformat()
                    log.info(f"Set expiration date for team {public_id}: {existing_settings['expires_at']}")
                except ValueError as e:
                    raise HTTPException(status_code=400, detail=f"Invalid date format: {str(e)}")
        
        # Update the team's sharing_settings
        team.sharing_settings = dict(existing_settings)
        
        # Explicitly mark the field as modified for SQLAlchemy
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(team, 'sharing_settings')
        
        db.commit()
        db.refresh(team)
        
        log.info(f"Updated sharing settings for team {public_id}: enabled = {existing_settings.get('enabled')}, uuid = {existing_settings.get('uuid')}, expires_at = {existing_settings.get('expires_at')}")
        
        return UpdateSharingSettingsResponse(
            success=True,
            message="Sharing settings updated successfully",
            enabled=existing_settings.get("enabled", False),
            uuid=existing_settings.get("uuid"),
            expires_at=existing_settings.get("expires_at")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        log.error(f"Failed to update sharing settings for team {public_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update sharing settings")


@router.get("/teams/{public_id}/sharing-settings/status")
async def get_sharing_status(
    public_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("USER", "ADMIN"))
):
    """
    Get sharing status for a team (read-only, accessible to all team members).
    Returns only whether sharing is enabled and active (not expired).
    Used by create page to determine if share options should be available.
    """
    log = new_logger("get_sharing_status")
    log.info(f"Getting sharing status for team: {public_id}")
    
    # Get current user info
    user_public_id = current_user.get('public_id') if isinstance(current_user, dict) else None
    user_team_id = current_user.get('team_id') if isinstance(current_user, dict) else None
    
    if not user_public_id:
        log.error("No user public_id found in current_user")
        raise HTTPException(status_code=401, detail="User authentication required")
    
    # Verify target team exists
    team = fetch_team_by_public_id(db, public_id)
    if not team:
        log.warning(f"Team not found: {public_id}")
        raise HTTPException(status_code=404, detail="Team not found")
    
    # Verify current user belongs to this team (for security)
    if user_team_id != team.public_id:
        log.warning(f"User {user_public_id} attempted to access sharing status for team {public_id} but belongs to team {user_team_id}")
        raise HTTPException(status_code=403, detail="Access denied: You can only access status for your own team")
    
    # Get sharing settings and log what we find
    sharing_settings = team.sharing_settings or {}
    log.info(f"Sharing settings for team {public_id}: {sharing_settings}")
    
    # Get enabled flag directly from settings
    enabled_flag = sharing_settings.get("enabled", False)
    log.info(f"Enabled flag from settings: {enabled_flag}")
    
    # Check if sharing is active using the utility function (includes expiry check)
    is_active = is_sharing_active(team)
    log.info(f"Is sharing active (after expiry check): {is_active}")
    
    return {
        "enabled": enabled_flag,  # Return the enabled flag directly (shows if admin enabled it)
        "is_active": is_active    # Also return the active status (includes expiry check)
    }


def is_sharing_active(team: Team) -> bool:
    """
    Check if sharing is currently active for a team.
    
    Returns True if:
    - sharing_settings is initialized (not null/empty)
    - sharing is enabled
    - expires_at is None (never expires) OR expires_at is in the future
    
    Args:
        team: Team model instance
        
    Returns:
        bool: True if sharing is active, False otherwise
    """
    # Check for null/uninitialized state
    if not team.sharing_settings:
        return False
    
    # Check enabled flag
    enabled = team.sharing_settings.get("enabled", False)
    if not enabled:
        return False
    
    # Check expiry date if present
    expires_at_str = team.sharing_settings.get("expires_at")
    if expires_at_str is None:
        return True  # No expiration
    
    try:
        expires_datetime = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
        now = datetime.now(expires_datetime.tzinfo if expires_datetime.tzinfo else None)
        return expires_datetime > now
    except (ValueError, TypeError):
        # If date parsing fails, assume not expired
        return True


# ================================
# Public team sharing endpoint
# ================================

class PublicPageSummary(BaseModel):
    """Summary of a publicly shared page for team listing"""
    public_id: str
    share_uuid: str
    name: str
    role: Optional[str] = None
    nickname: Optional[str] = None
    pronunciation_text: Optional[str] = None
    pronunciation_recording_url: Optional[str] = None
    location: Optional[str] = None
    wave_gif_url: Optional[str] = None
    profile_photo_url: Optional[str] = None

class PublicTeamInfo(BaseModel):
    """Team information for public sharing view"""
    public_id: str
    organization_name: str
    company_logo_url: Optional[str] = None
    color_scheme: Optional[str] = None
    color_scheme_data: Optional[Dict[str, Any]] = None

class PublicTeamPagesResponse(BaseModel):
    """Response containing team info and list of publicly shared pages"""
    team: PublicTeamInfo
    pages: List[PublicPageSummary]

@router.get("/public/teams/{share_uuid}/pages", response_model=PublicTeamPagesResponse)
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(OperationalError),
    before_sleep=before_sleep_log(team_retry_logger, logging.WARNING)
)
def get_public_team_pages(
    share_uuid: str, 
    search: Optional[str] = Query(None, description="Full-text search query"),
    db: Session = Depends(get_db), 
    current_user=Depends(require_roles("PUBLIC", "PRE_SIGNUP", "USER", "ADMIN"))
):
    """
    Public endpoint returning all publicly shared pages for a team by team sharing UUID.
    Requires valid JWT signature (verifies request comes from Next.js).
    Validates team sharing is enabled and active.
    Supports full-text search across all user data.
    """
    log = new_logger("get_public_team_pages")
    log.info(f"Fetching public team pages with share_uuid: {share_uuid}, search: {search}")
    
    try:
        # Find team by sharing UUID using PostgreSQL JSONB query for efficient lookup with GIN index
        target_team = db.query(Team).filter(
            Team.sharing_settings.isnot(None),
            text("sharing_settings->>'uuid' = :share_uuid").bindparams(share_uuid=share_uuid)
        ).first()
        
        if not target_team:
            log.warning(f"Team not found for share_uuid: {share_uuid}")
            raise HTTPException(status_code=404, detail="Team not found")
        
        log.info(f"Found team {target_team.public_id} for share_uuid: {share_uuid}")
        
        # Verify team sharing is active
        if not is_sharing_active(target_team):
            log.warning(f"Team sharing is not active for share_uuid: {share_uuid}, team: {target_team.public_id}")
            raise HTTPException(status_code=404, detail="Team not found")
        
        # Query all users in the team where is_shareable = true and share_uuid IS NOT NULL
        query = db.query(WelcomepageUser).filter(
            WelcomepageUser.team_id == target_team.id,
            WelcomepageUser.is_shareable == True,
            WelcomepageUser.share_uuid.isnot(None)
        )
        
        # Apply full-text search filter if provided
        if search:
            # Use PostgreSQL full-text search with search_vector column
            # For prefix matching (partial words), we use to_tsquery with :* operator
            # For full words/phrases, we use plainto_tsquery
            search_terms = search.strip().split()
            if len(search_terms) == 1 and len(search.strip()) < 20:
                # Single short term - use prefix matching for better partial word support
                search_query_str = """
                    to_tsquery('english', 
                        regexp_replace(
                            regexp_replace(:search_term, '[^a-zA-Z0-9\\s]', '', 'g'),
                            '\\s+', ' & ', 'g'
                        ) || ':*'
                    )
                """
            else:
                # Multiple words or long term - use plainto_tsquery (handles phrases better)
                search_query_str = "plainto_tsquery('english', :search_term)"
            
            query = query.filter(text(f"search_vector @@ ({search_query_str})").bindparams(search_term=search))
        
        shared_pages = query.all()
        
        log.info(f"Found {len(shared_pages)} publicly shared pages for team {target_team.public_id}")
        
        # Build team info
        team_info = PublicTeamInfo(
            public_id=target_team.public_id,
            organization_name=target_team.organization_name,
            company_logo_url=target_team.company_logo_url,
            color_scheme=target_team.color_scheme,
            color_scheme_data=target_team.color_scheme_data
        )
        
        # Build page summaries
        page_summaries = [
            PublicPageSummary(
                public_id=page.public_id,
                share_uuid=page.share_uuid,
                name=page.name,
                role=page.role,
                nickname=page.nickname,
                pronunciation_text=page.pronunciation_text,
                pronunciation_recording_url=page.pronunciation_recording_url,
                location=page.location,
                wave_gif_url=page.wave_gif_url,
                profile_photo_url=page.profile_photo_url
            )
            for page in shared_pages
        ]
        
        return PublicTeamPagesResponse(
            team=team_info,
            pages=page_summaries
        )
        
    except HTTPException:
        raise
    except OperationalError:
        db.rollback()
        raise
    except Exception as e:
        log.error(f"Non-retryable error in get_public_team_pages: {e}")
        raise HTTPException(status_code=500, detail="Internal error")


# =====================
# Allowed Email Domains
# =====================

class DomainSecuritySettings(BaseModel):
    domain_check_enabled: bool = False
    allowed_domains: List[str] = []


@router.get("/teams/{public_id}/security-settings")
async def get_security_settings(
    public_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("ADMIN"))
):
    """
    Get security settings for a team (allowed email domains).
    Only ADMIN users can access security settings.
    """
    log = new_logger("get_security_settings")
    log.info(f"Getting security settings for team: {public_id}")

    user_public_id = current_user.get('public_id') if isinstance(current_user, dict) else None
    user_team_id = current_user.get('team_id') if isinstance(current_user, dict) else None

    team = fetch_team_by_public_id(db, public_id)
    if not team:
        log.warning(f"Team not found: {public_id}")
        raise HTTPException(status_code=404, detail="Team not found")

    if user_team_id != team.public_id:
        log.warning(f"User {user_public_id} attempted to access security settings for team {public_id} but belongs to team {user_team_id}")
        raise HTTPException(status_code=403, detail="Access denied: You can only access settings for your own team")

    settings = team.security_settings or {}
    # Normalize response
    response = {
        "domain_check_enabled": bool(settings.get("domain_check_enabled", False)),
        "allowed_domains": settings.get("allowed_domains") or []
    }
    log.info(f"Retrieved security settings for team {public_id}: {response}")
    return response


@router.patch("/teams/{public_id}/security-settings")
async def update_security_settings(
    public_id: str,
    request: DomainSecuritySettings,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("ADMIN"))
):
    """
    Update security settings for a team (allowed email domains).
    Only ADMIN users can update security settings.
    """
    log = new_logger("update_security_settings")
    log.info(f"Updating security settings for team: {public_id}")

    user_public_id = current_user.get('public_id') if isinstance(current_user, dict) else None
    user_team_id = current_user.get('team_id') if isinstance(current_user, dict) else None

    team = fetch_team_by_public_id(db, public_id)
    if not team:
        log.warning(f"Team not found: {public_id}")
        raise HTTPException(status_code=404, detail="Team not found")

    if user_team_id != team.public_id:
        log.warning(f"User {user_public_id} attempted to update security settings for team {public_id} but belongs to team {user_team_id}")
        raise HTTPException(status_code=403, detail="Access denied: You can only update settings for your own team")

    try:
        # Normalize incoming domains: trim, lowercase, strip leading '@'
        def _normalize_domain(s: str) -> str:
            s = (s or "").strip().lower()
            if s.startswith("@"): s = s[1:]
            return s

        normalized_domains = []
        for d in (request.allowed_domains or []):
            nd = _normalize_domain(d)
            if nd: normalized_domains.append(nd)

        existing = team.security_settings or {}
        existing["domain_check_enabled"] = bool(request.domain_check_enabled)
        existing["allowed_domains"] = normalized_domains

        team.security_settings = dict(existing)
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(team, 'security_settings')
        db.commit()
        db.refresh(team)

        response = {
            "domain_check_enabled": existing["domain_check_enabled"],
            "allowed_domains": existing["allowed_domains"],
        }
        log.info(f"Updated security settings for team {public_id}: {response}")
        return response
    except Exception as e:
        db.rollback()
        log.error(f"Failed to update security settings for team {public_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update security settings")