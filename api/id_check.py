from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models.team import Team
from models.welcomepage_user import WelcomepageUser
from pydantic import BaseModel
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

class IDCheckRequest(BaseModel):
    id: str
    type: str  # "user" or "team"

class IDCheckResponse(BaseModel):
    available: bool
    id: str
    type: str

@router.post("/check-id-availability", response_model=IDCheckResponse)
async def check_id_availability(
    request: IDCheckRequest,
    db: Session = Depends(get_db)
):
    """
    Check if a proposed public ID is available (not already in use).
    
    Args:
        request: Contains the ID to check and type ("user" or "team")
        
    Returns:
        IDCheckResponse with availability status
    """
    try:
        logger.info(f"Checking ID availability: {request.id} (type: {request.type})")
        
        # Validate input
        if not request.id or len(request.id.strip()) == 0:
            raise HTTPException(status_code=400, detail="ID cannot be empty")
            
        if request.type not in ["user", "team"]:
            raise HTTPException(status_code=400, detail="Type must be 'user' or 'team'")
        
        # Check appropriate table based on type
        existing_record = None
        if request.type == "user":
            existing_record = db.query(WelcomepageUser).filter_by(public_id=request.id).first()
        elif request.type == "team":
            existing_record = db.query(Team).filter_by(public_id=request.id).first()
        
        is_available = existing_record is None
        
        logger.info(f"ID {request.id} ({'available' if is_available else 'taken'})")
        
        return IDCheckResponse(
            available=is_available,
            id=request.id,
            type=request.type
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking ID availability: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to check ID availability")
