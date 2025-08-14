from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, PlainTextResponse
from sqlalchemy.orm import Session
from typing import Optional
import os
import json

from database import get_db
from services.slack_installation_service import SlackInstallationService
from services.slack_event_service import SlackEventService
from schemas.slack import SlackOAuthStartResponse, SlackInstallationResponse
from utils.jwt_auth import get_current_user
from utils.logger_factory import new_logger
from utils.jwt_auth import require_roles
from utils.slack_signature_verifier import SlackSignatureVerifier

router = APIRouter()


@router.get("/oauth/start", response_model=SlackOAuthStartResponse)
async def start_slack_oauth(
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("ADMIN"))
):
    """
    Start Slack OAuth flow
    This endpoint requires admin authentication
    Uses the authenticated user's team_public_id
    """
    log = new_logger("start_slack_oauth")
    try:
        
        # Get team_public_id from authenticated user
        team_public_id = current_user.get("team_id")
        if not team_public_id:
            raise HTTPException(status_code=400, detail="Team ID not found in user context")
        
        service = SlackInstallationService(db)
        result = service.start_oauth_flow(team_public_id)
        
        log.info(f"Started Slack OAuth flow for team {team_public_id} with state: {result.state} authorize url: {result.authorize_url}")
        return result
        
    except ValueError as e:
        log.error(f"Configuration error: {str(e)}")
        raise HTTPException(status_code=500, detail="Slack integration not properly configured")
    except Exception as e:
        log.error(f"Failed to start Slack OAuth: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to start Slack installation")


@router.get("/oauth/callback")
async def slack_oauth_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Handle Slack OAuth callback
    This endpoint is called by Slack after user authorizes the app
    The team_public_id is extracted from the state parameter
    """
    log = new_logger("slack_oauth_callback")
    try:
        # Check for user cancellation
        if error == "access_denied":
            log.info("User canceled Slack OAuth installation")
            return RedirectResponse(
                url=os.getenv("WEBAPP_URL") + "/integration/slack/oauthcancelled",
                status_code=302
            )
        
        # Validate required parameters
        if not code or not state:
            log.error("Missing required OAuth parameters")
            return RedirectResponse(
                url=os.getenv("WEBAPP_URL") + "/integration/slack/installerror",
                status_code=302
            )
        
        service = SlackInstallationService(db)
        # Team ID is now extracted from the state parameter
        result = service.handle_oauth_callback(code, state)
        
        log.info(f"Slack installation completed (Slack team: {result.team_id})")
        
        # Redirect to team settings page with success parameter
        return RedirectResponse(
            url=f"{os.getenv('WEBAPP_URL')}/team-settings?slack_success=true",
            status_code=302
        )
        
    except ValueError as e:
        log.error(f"OAuth validation error: {str(e)}")
        return RedirectResponse(
            url=os.getenv("WEBAPP_URL") + "/integration/slack/installerror",
            status_code=302
        )
    except Exception as e:
        log.error(f"OAuth callback failed: {str(e)}")
        return RedirectResponse(
            url=os.getenv("WEBAPP_URL") + "/integration/slack/installerror",
            status_code=302
        )


@router.get("/installation/{team_public_id}")
async def get_slack_installation(
    team_public_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Get Slack installation status for a team
    """
    log = new_logger("get_slack_installation")
    try:
        # Verify user has access to this team
        user_team_id = current_user.get("team_id")
        if user_team_id != team_public_id:
            raise HTTPException(status_code=403, detail="Access denied to this team")
        
        service = SlackInstallationService(db)
        installation = service.get_installation_for_team(team_public_id)
        
        if not installation:
            return {"installed": False, "message": "Slack not installed for this team"}
        
        # Return safe installation info (no tokens)
        return {
            "installed": True,
            "team_id": installation.team_id,
            "team_name": installation.team_name,
            "enterprise_id": installation.enterprise_id,
            "enterprise_name": installation.enterprise_name,
            "is_enterprise_install": installation.is_enterprise_install,
            "installed_at": installation.installed_at,
            "bot_scopes": installation.bot_scopes,
            "user_scopes": installation.user_scopes
        }
        
    except Exception as e:
        log.error(f"Failed to get installation status: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get installation status")


@router.delete("/installation/{team_public_id}")
async def uninstall_slack(
    team_public_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Uninstall Slack integration for a team
    Requires ADMIN role
    """
    log = new_logger("uninstall_slack")
    try:
        # Verify user has admin role
        if current_user.get("role") != "ADMIN":
            raise HTTPException(status_code=403, detail="Admin access required")
        
        # Verify user has access to this team
        user_team_id = current_user.get("team_id")
        if user_team_id != team_public_id:
            raise HTTPException(status_code=403, detail="Access denied to this team")
        
        service = SlackInstallationService(db)
        success = service.uninstall_slack(team_public_id)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to uninstall Slack")
        
        log.info(f"Slack uninstalled for team {team_public_id} by user {current_user.get('public_id')}")
        
        return {"success": True, "message": "Slack integration removed successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to uninstall Slack: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to uninstall Slack")


@router.post("/cleanup-expired-states")
async def cleanup_expired_states(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Cleanup expired OAuth states (admin only)
    This can be called periodically to clean up the database
    """
    log = new_logger("cleanup_expired_states")
    try:
        # Verify user has admin role
        if current_user.get("role") != "ADMIN":
            raise HTTPException(status_code=403, detail="Admin access required")
        
        service = SlackInstallationService(db)
        service.state_manager.cleanup_expired_states()
        
        return {"success": True, "message": "Expired states cleaned up"}
        
    except Exception as e:
        log.error(f"Failed to cleanup expired states: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to cleanup expired states")


@router.get("/custom-profile-field/{team_public_id}")
async def check_custom_profile_field(
    team_public_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Check if the custom 'Welcomepage' profile field is configured in Slack workspace
    Requires ADMIN role and team access
    """
    log = new_logger("check_custom_profile_field")
    try:
        # Verify user has admin role
        if current_user.get("role") != "ADMIN":
            raise HTTPException(status_code=403, detail="Admin access required")
        
        # Verify user has access to this team
        user_team_id = current_user.get("team_id")
        if user_team_id != team_public_id:
            raise HTTPException(status_code=403, detail="Access denied to this team")
        
        service = SlackInstallationService(db)
        profile_configured = service.check_custom_profile_field(team_public_id)
        
        log.info(f"Custom profile field check for team {team_public_id}: {profile_configured}")
        
        return {
            "profile_configured": profile_configured,
            "team_id": team_public_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to check custom profile field: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to check custom profile field")


@router.post("/events")
async def handle_slack_events(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Handle Slack events webhook
    This endpoint receives events from Slack including app_uninstalled, team_join, etc.
    """
    log = new_logger("handle_slack_events")
    try:
        # Get request headers and body for signature verification
        body = await request.body()
        timestamp = request.headers.get("X-Slack-Request-Timestamp")
        signature = request.headers.get("X-Slack-Signature")
        
        if not timestamp or not signature:
            log.error("Missing required Slack headers")
            raise HTTPException(status_code=400, detail="Missing required headers")
        
        # Verify Slack signature
        verifier = SlackSignatureVerifier()
        if not verifier.verify_signature(body, timestamp, signature):
            log.error("Invalid Slack signature")
            raise HTTPException(status_code=403, detail="Invalid Slack signature")
        
        # Parse the event payload
        payload = json.loads(body.decode('utf-8'))
        log.info(f"Received Slack event: {payload.get('type', 'unknown')}")
        
        # Handle URL verification challenge - return plain string like Flask version
        if payload.get("type") == "url_verification":
            challenge = payload.get("challenge")
            if challenge:
                log.info("Responding to Slack URL verification challenge")
                return PlainTextResponse(challenge)
            else:
                log.error("No challenge found in URL verification request")
                raise HTTPException(status_code=400, detail="No challenge found")
        
        # Handle other events using the service
        service = SlackEventService(db)
        result = service.handle_event(payload)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to handle Slack event: {str(e)}")
        # Return 200 to prevent Slack from retrying
        return {"status": "error", "message": str(e)}
