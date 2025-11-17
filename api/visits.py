from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
from models.page_visit import PageVisit
from models.welcomepage_user import WelcomepageUser
from schemas.page_visit import RecordVisitRequest, UpdateVisitDurationRequest, PageVisitResponse, VisitStatsResponse
from utils.jwt_auth import get_current_user
from utils.logger_factory import new_logger
import httpx
from typing import Optional
from datetime import datetime

router = APIRouter()


async def get_visitor_location(ip_address: str) -> dict:
    """
    Get visitor location using free tier IP geolocation service.
    Using ipapi.co which provides 1000 free requests per day.
    """
    log = new_logger("get_visitor_location")
    
    try:
        # Skip localhost and private IPs
        if ip_address in ['127.0.0.1', 'localhost'] or ip_address.startswith('192.168.') or ip_address.startswith('10.'):
            return {"country": None, "region": None, "city": None}
        
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"https://ipapi.co/{ip_address}/json/")
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "country": data.get("country_code"),  # ISO 2-letter code
                    "region": data.get("region"),
                    "city": data.get("city")
                }
            else:
                log.warning(f"IP geolocation API returned {response.status_code}")
                return {"country": None, "region": None, "city": None}
                
    except Exception as e:
        log.error(f"Failed to get visitor location: {str(e)}")
        return {"country": None, "region": None, "city": None}


def get_client_ip(request: Request) -> str:
    """Extract client IP address from request headers for geolocation."""
    log = new_logger("get_client_ip")
    
    # Debug: Log all relevant headers
    headers_to_check = [
        "x-vercel-forwarded-for",
        "X-Forwarded-For", 
        "X-Real-IP",
        "x-forwarded-for",
        "x-real-ip"
    ]
    
    log.info("=== IP Header Debug ===")
    for header in headers_to_check:
        value = request.headers.get(header)
        if value:
            log.info(f"{header}: {value}")
    log.info("=== End IP Headers ===")
    
    # Try Vercel-specific headers first (for production deployments)
    vercel_ip = request.headers.get("x-vercel-forwarded-for")
    if vercel_ip:
        log.info(f"Using Vercel forwarded IP: {vercel_ip}")
        return vercel_ip.split(",")[0].strip()
    
    # Check for standard forwarded IP (common in production behind proxies)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Take the first IP if there are multiple
        client_ip = forwarded_for.split(",")[0].strip()
        log.info(f"Using X-Forwarded-For IP: {client_ip}")
        return client_ip
    
    # Check other common headers
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        log.info(f"Using X-Real-IP: {real_ip}")
        return real_ip
    
    # Fall back to direct client IP
    fallback_ip = request.client.host if request.client else "unknown"
    log.info(f"Using fallback IP: {fallback_ip}")
    return fallback_ip


@router.post("/visits/record", response_model=PageVisitResponse)
async def record_visit(
    visit_data: RecordVisitRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Record a visit to a welcomepage.
    All visitors are authenticated users.
    """
    log = new_logger("record_visit")
    log.info(f"Recording visit to user {visit_data.visited_user_public_id}")
    
    # Find the visited user
    visited_user = db.query(WelcomepageUser).filter(
        WelcomepageUser.public_id == visit_data.visited_user_public_id
    ).first()
    
    if not visited_user:
        log.warning(f"Visited user not found: {visit_data.visited_user_public_id}")
        raise HTTPException(status_code=404, detail="User not found")
    
    # Get visitor information (always authenticated)
    visitor_public_id = current_user.get('user_id')  # This should be the public_id
    log.info(f"Authenticated visitor: {visitor_public_id}")
    log.info(f"Full current_user object: {current_user}")
    log.info(f"visitor_public_id type: {type(visitor_public_id)}, length: {len(str(visitor_public_id))}")
    
    if not visitor_public_id:
        log.error("No visitor public_id found in authenticated user")
        raise HTTPException(status_code=401, detail="Invalid authentication")
    
    # Prevent users from recording visits to their own page
    if visitor_public_id == visit_data.visited_user_public_id:
        log.info(f"User attempted to record visit to their own page: {visitor_public_id}")
        raise HTTPException(status_code=400, detail="Cannot record visit to your own page")
    
    # Get client IP for geolocation - prioritize real_client_ip from request body
    if visit_data.real_client_ip:
        client_ip = visit_data.real_client_ip
        log.info(f"Using real client IP from request body: {client_ip}")
    else:
        client_ip = get_client_ip(request)
        log.info(f"Using client IP from headers: {client_ip}")
    
    user_agent = request.headers.get("User-Agent", "")
    log.info(f"Final client IP for geolocation: {client_ip}")
    
    # Get visitor location
    location_data = await get_visitor_location(client_ip)
    log.info(f"Location data received: {location_data}")
    
    try:
        # Create visit record
        visit = PageVisit(
            visited_user_id=visited_user.id,
            visitor_public_id=visitor_public_id,
            visitor_country=location_data["country"],
            visitor_region=location_data["region"],
            visitor_city=location_data["city"],
            referrer=visit_data.referrer,
            user_agent=user_agent,
            session_id=visit_data.session_id
        )
        
        db.add(visit)
        db.commit()
        db.refresh(visit)
        
        log.info(f"Visit recorded successfully: ID {visit.id} by visitor {visitor_public_id}")
        
        return PageVisitResponse.from_orm(visit)
        
    except Exception as e:
        db.rollback()
        log.error(f"Failed to record visit: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to record visit")


@router.patch("/visits/{visit_id}/duration")
async def update_visit_duration(
    visit_id: int,
    duration_data: UpdateVisitDurationRequest,
    db: Session = Depends(get_db)
):
    """
    Update the duration of a visit when the user leaves the page.
    """
    log = new_logger("update_visit_duration")
    log.info(f"Updating duration for visit {visit_id}: {duration_data.duration_seconds}s")
    
    visit = db.query(PageVisit).filter(PageVisit.id == visit_id).first()
    
    if not visit:
        log.warning(f"Visit not found: {visit_id}")
        raise HTTPException(status_code=404, detail="Visit not found")
    
    try:
        visit.visit_duration_seconds = duration_data.duration_seconds
        visit.visit_end_time = func.now()
        
        db.commit()
        
        log.info(f"Visit duration updated successfully")
        
        return {"success": True, "message": "Visit duration updated"}
        
    except Exception as e:
        db.rollback()
        log.error(f"Failed to update visit duration: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update visit duration")


@router.patch("/visits/{visit_id}/end")
async def record_visit_end(
    visit_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Record the end time of a visit when the user leaves the page.
    Duration will be calculated from start_time and end_time.
    """
    log = new_logger("record_visit_end")
    log.info(f"Recording end time for visit {visit_id}")
    
    try:
        # Find the visit
        visit = db.query(PageVisit).filter(PageVisit.id == visit_id).first()
        
        if not visit:
            log.warning(f"Visit not found: {visit_id}")
            raise HTTPException(status_code=404, detail="Visit not found")
        
        # Update the end time
        end_time = datetime.utcnow()
        visit.visit_end_time = end_time
        
        # Calculate and store duration in seconds
        if visit.visit_start_time:
            duration_seconds = int((end_time - visit.visit_start_time).total_seconds())
            visit.visit_duration_seconds = duration_seconds
            log.info(f"Calculated visit duration: {duration_seconds} seconds")
        else:
            log.warning(f"No start time found for visit {visit_id}, cannot calculate duration")
        
        db.commit()
        
        log.info(f"Visit end time and duration recorded successfully for visit {visit_id}")
        
        return {"success": True, "message": "Visit end time recorded"}
        
    except Exception as e:
        db.rollback()
        log.error(f"Failed to record visit end time: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to record visit end time")


@router.get("/visits/stats/{user_public_id}", response_model=VisitStatsResponse)
async def get_visit_stats(
    user_public_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Get visit statistics for a specific user.
    For testing purposes - in production, this would be integrated into the team members API.
    """
    log = new_logger("get_visit_stats")
    log.info(f"Getting visit stats for user {user_public_id}")
    
    # Find the user
    user = db.query(WelcomepageUser).filter(
        WelcomepageUser.public_id == user_public_id
    ).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    try:
        # Get visit statistics
        visits_query = db.query(PageVisit).filter(PageVisit.visited_user_id == user.id)
        
        total_visits = visits_query.count()
        
        # Count unique visitors (all visitors are authenticated users)
        # Exclude visits made by the user to their own page
        unique_visits_query = visits_query.filter(PageVisit.visitor_public_id != user.public_id)
        unique_visits = unique_visits_query.distinct(PageVisit.visitor_public_id).count()
        
        # Average duration (only for visits with duration data, excluding own visits)
        avg_duration = db.query(func.avg(PageVisit.visit_duration_seconds)).filter(
            PageVisit.visited_user_id == user.id,
            PageVisit.visitor_public_id != user.public_id,
            PageVisit.visit_duration_seconds.isnot(None)
        ).scalar()
        
        # Count unique countries (excluding own visits)
        countries_reached = db.query(func.count(func.distinct(PageVisit.visitor_country))).filter(
            PageVisit.visited_user_id == user.id,
            PageVisit.visitor_public_id != user.public_id,
            PageVisit.visitor_country.isnot(None)
        ).scalar() or 0
        
        # Get recent visitors (last 10 visitors, excluding own visits)
        recent_visitors = db.query(PageVisit.visitor_public_id).filter(
            PageVisit.visited_user_id == user.id,
            PageVisit.visitor_public_id != user.public_id
        ).order_by(PageVisit.visit_start_time.desc()).limit(10).all()
        
        recent_visitor_ids = [v.visitor_public_id for v in recent_visitors if v.visitor_public_id]
        
        return VisitStatsResponse(
            unique_visits=unique_visits,
            total_visits=total_visits,
            avg_duration_seconds=float(avg_duration) if avg_duration else None,
            countries_reached=countries_reached,
            recent_visitors=recent_visitor_ids
        )
        
    except Exception as e:
        log.error(f"Failed to get visit stats: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get visit statistics")
