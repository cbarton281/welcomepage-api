from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from database import get_db
from models.team import Team
from services.slack_installation_service import SlackInstallationService
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from utils.logger_factory import new_logger

router = APIRouter()

@router.get("/api/slack/channels", response_model=List[Dict[str, str]])
async def search_channels(
    query: str = Query(..., min_length=3),
    team_public_id: str = Query(...),
    db: Session = Depends(get_db)
):
    """
    Search for Slack channels in the team's workspace
    Requires minimum 3 characters for search
    Returns list of channel objects with id and name
    """
    log = new_logger(f"search_channels_{team_public_id}")
    
    try:
        # Get team data
        team = db.query(Team).filter_by(public_id=team_public_id).first()
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        
        # Get Slack installation
        installation = SlackInstallationService.get_installation_for_team(team, db)
        if not installation:
            raise HTTPException(
                status_code=400, 
                detail="No Slack integration found for this team"
            )
        
        # Initialize Slack client
        client = WebClient(token=installation.bot_token)
        
        # Search channels using conversations.list
        # Note: search is done client-side since Slack API doesn't support search
        response = client.conversations_list(
            types="public_channel",  # Only search public channels
            exclude_archived=True,
            limit=100  # Reasonable limit for search results
        )
        
        if not response["ok"]:
            raise SlackApiError("Failed to fetch channels", response)
            
        # Filter channels by query (case-insensitive)
        query = query.lower()
        channels = [
            {"id": channel["id"], "name": channel["name"]}
            for channel in response["channels"]
            if query in channel["name"].lower()
        ]
        
        return channels[:20]  # Limit results
        
    except SlackApiError as e:
        log.error(f"Slack API error: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=f"Slack API error: {e.response.get('error', 'Unknown error')}"
        )
    except Exception as e:
        log.error(f"Error searching channels: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail="Internal server error"
        )
