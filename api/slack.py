from fastapi import APIRouter, Depends, HTTPException, Query, Request, Body, Form
from fastapi.responses import RedirectResponse, PlainTextResponse, JSONResponse
from sqlalchemy.orm import Session
from typing import Optional
import os
import json
import logging
import re
from urllib.parse import parse_qs

from database import get_db
from services.slack_installation_service import SlackInstallationService
from models.slack_pending_install import SlackPendingInstall
from models.slack_state_store import SlackStateStore
from models.team import Team
from models.welcomepage_user import WelcomepageUser
from schemas.slack import SlackInstallationData, SlackOAuthStartResponse, SlackInstallationResponse
from utils.jwt_auth import get_current_user
from utils.logger_factory import new_logger
from utils.jwt_auth import require_roles
from utils.slack_signature_verifier import SlackSignatureVerifier
from slack import WebClient
from services.slack_event_service import SlackEventService
from services.slack_blocks_service import SlackBlocksService
from services.slack_publish_service import SlackPublishService
from models.welcomepage_user import WelcomepageUser

router = APIRouter()


@router.get("/oauth/start", response_model=SlackOAuthStartResponse)
async def start_slack_oauth(
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("ADMIN")),
    context: Optional[str] = Query(None),
    return_path: Optional[str] = Query(None),
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
        initiator_public_user_id = current_user.get("public_id")
        result = service.start_oauth_flow(
            team_public_id,
            initiator_public_user_id=initiator_public_user_id,
            context=context,
            return_path=return_path,
        )
        
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
        if not code:
            log.error("Missing required OAuth 'code' parameter")
            return RedirectResponse(
                url=os.getenv("WEBAPP_URL") + "/integration/slack/installerror",
                status_code=302
            )

        service = SlackInstallationService(db)

        # Helper: parse decorated state into base/ctx/ret
        def parse_state(s: str):
            base = s or ""
            ctx = None
            ret = None
            if "__ctx=" in base:
                parts = base.split("__ctx=", 1)
                base = parts[0]
                tail = parts[1]
                if "__ret=" in tail:
                    ctx, ret = tail.split("__ret=", 1)
                else:
                    ctx = tail
            return base, ctx, ret

        # If state exists, this is our app-initiated flow (Scenario 1)
        if state:
            base_state, ctx, ret = parse_state(state)
            result = service.handle_oauth_callback(code, base_state)
            log.info(f"Slack installation completed (Slack team: {result.team_id}) ctx={ctx} ret={ret}")
            # Perform browser redirect directly from backend callback so Slack lands users correctly
            if ctx == "publish_flow":
                target = ret or "/create?afterSlack=1"
                return RedirectResponse(url=f"{os.getenv('WEBAPP_URL')}{target}", status_code=302)
            elif ctx == "signup_flow":
                # For signup flow, redirect to the return path (which should include afterSlack=1)
                target = ret or "/?afterSlack=1"
                return RedirectResponse(url=f"{os.getenv('WEBAPP_URL')}{target}", status_code=302)
            return RedirectResponse(
                url=f"{os.getenv('WEBAPP_URL')}/team-settings?slack_success=true",
                status_code=302
            )

        # No state: marketplace install (Scenarios 2–4). Create pending and redirect with nonce
        installation_data = service.exchange_code_without_state(code)
        nonce = service.create_pending_install(installation_data)
        log.info(f"Created pending Slack installation, nonce={nonce}")
        return RedirectResponse(
            url=f"{os.getenv('WEBAPP_URL')}/integration/slack/link?nonce={nonce}",
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


@router.get("/oauth/pending/{nonce}")
async def get_pending_install(nonce: str, db: Session = Depends(get_db)):
    """Public endpoint to fetch safe info about a pending Slack installation."""
    log = new_logger("get_pending_install")
    try:
        service = SlackInstallationService(db)
        pending = service.get_pending_install(nonce)
        if not pending:
            raise HTTPException(status_code=404, detail="Pending installation not found or expired")
        return {
            "nonce": pending.nonce,
            "slack_team_id": pending.slack_team_id,
            "slack_team_name": pending.slack_team_name,
            "expires_at": pending.expires_at.isoformat() if pending.expires_at else None,
            "consumed": pending.consumed,
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to fetch pending install: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch pending installation")


@router.post("/oauth/complete-link")
async def complete_link_from_pending(
    nonce: str = Body(..., embed=True),
    current_user: dict = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
):
    """ADMIN-only: Apply a pending Slack installation to the current user's team."""
    log = new_logger("complete_link_from_pending")
    try:
        service = SlackInstallationService(db)
        pending = service.get_pending_install(nonce)
        if not pending:
            raise HTTPException(status_code=404, detail="Pending installation not found or expired")

        # Build model and apply
        install_data = SlackInstallationData(**(pending.installation_json or {}))
        team_public_id = current_user.get("team_id")
        if not team_public_id:
            raise HTTPException(status_code=400, detail="User team not found")
        initiator_public_user_id = current_user.get("public_id")
        service.apply_installation_to_team(team_public_id, install_data, initiator_public_user_id=initiator_public_user_id)
        service.consume_pending_install(nonce)

        return {"success": True, "team_public_id": team_public_id}
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to complete link from pending: {e}")
        raise HTTPException(status_code=500, detail="Failed to complete Slack linking")


@router.post("/oauth/create-team-from-pending")
async def create_team_from_pending(
    nonce: str = Body(..., embed=True),
    db: Session = Depends(get_db),
):
    """Create a brand-new team from a pending Slack installation (Scenario 4). Public endpoint; will create a draft team."""
    log = new_logger("create_team_from_pending")
    try:
        service = SlackInstallationService(db)
        pending = service.get_pending_install(nonce)
        if not pending:
            raise HTTPException(status_code=404, detail="Pending installation not found or expired")

        install_data = SlackInstallationData(**(pending.installation_json or {}))
        team = service.create_team_from_install(install_data)
        service.consume_pending_install(nonce)

        return {"success": True, "team_public_id": team.public_id}
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to create team from pending: {e}")
        raise HTTPException(status_code=500, detail="Failed to create team from pending installation")


@router.get("/installation/{team_public_id}")
async def get_slack_installation(
    team_public_id: str,
    db: Session = Depends(get_db),
    current_user =Depends(require_roles("ADMIN"))
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
        
        # Get team data directly
        team = db.query(Team).filter_by(public_id=team_public_id).first()
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        
        if not team.slack_settings or not isinstance(team.slack_settings, dict):
            raise HTTPException(status_code=404, detail="No Slack integration found for this team")
        
        slack_app_data = team.slack_settings.get("slack_app")
        if not slack_app_data or not isinstance(slack_app_data, dict):
            raise HTTPException(status_code=404, detail="No Slack integration found for this team")
        
        # Return safe installation info (no tokens) - flatten the structure to match frontend expectations
        return {
            "team_id": slack_app_data.get("team_id"),
            "team_name": slack_app_data.get("team_name"),
            "enterprise_id": slack_app_data.get("enterprise_id"),
            "enterprise_name": slack_app_data.get("enterprise_name"),
            "is_enterprise_install": slack_app_data.get("is_enterprise_install", False),
            "installed_at": slack_app_data.get("installed_at"),
            "bot_scopes": slack_app_data.get("bot_scopes", []),
            "user_scopes": slack_app_data.get("user_scopes", [])
        }
        
    except Exception as e:
        log.error(f"Failed to get installation status: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get installation status")


@router.get("/status/{team_public_id}")
async def get_slack_status(
    team_public_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Get minimal Slack status for regular users (read-only)
    Returns only: hasInstallation (bool) and publishChannel (string|null)
    """
    log = new_logger("get_slack_status")
    log.info(f"🔍 SLACK STATUS REQUEST - User ID: {current_user.get('user_id')}, Role: {current_user.get('role')}, Team ID: {current_user.get('team_id')} Team Public ID: {team_public_id}")
    try:
        # Verify user has access to this team
        user_team_id = current_user.get("team_id")
        if user_team_id != team_public_id:
            raise HTTPException(status_code=403, detail="Access denied to this team")
        
        # Get team to access slack_settings directly
        team = db.query(Team).filter_by(public_id=team_public_id).first()
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        
        # Check if Slack installation exists in team settings
        slack_settings = team.slack_settings or {}
        slack_app_data = slack_settings.get("slack_app")
        
        if not slack_app_data or not isinstance(slack_app_data, dict):
            return {
                "hasInstallation": False,
                "publishChannel": None
            }
        
        # Get publish_channel from team.slack_settings (not from installation data)
        slack_settings = team.slack_settings or {}
        publish_channel_data = slack_settings.get("publish_channel")
        
        # Return minimal status data for regular users
        return {
            "hasInstallation": True,
            "publishChannel": publish_channel_data,  # Expect object with id and name
            "teamName": slack_app_data.get("team_name")
        }
        
    except Exception as e:
        log.error(f"Failed to get Slack status: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get Slack status")


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


@router.get("/channels")
async def search_slack_channels(
    query: str = Query(..., min_length=3, description="Channel name search query (minimum 3 characters)"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Search for public Slack channels in the team's connected workspace.
    Requires minimum 3 characters for search query.
    """
    log = new_logger("search_slack_channels")
    log.info(f"Starting channel search for query: '{query}'")
    log.info(f"Current user: {current_user}")
    
    try:
        # Resolve team context
        user_public_id = current_user.get('public_id')
        user_role = current_user.get('role')
        user_team_public_id = current_user.get('team_id')
        log.info(f"Resolving team for Slack channel search. requester public_id={user_public_id} role={user_role} team_public_id={user_team_public_id}")

        team = None
        if user_role == 'PRE_SIGNUP':
            # Anonymous/temporary users are not in DB; use team_id from JWT
            from models.team import Team
            team = db.query(Team).filter_by(public_id=user_team_public_id).first()
            if not team:
                log.error(f"Team not found for public_id: {user_team_public_id}")
                raise HTTPException(status_code=404, detail="Team not found")
        else:
            # Authenticated users should exist in DB
            user = db.query(WelcomepageUser).filter_by(public_id=user_public_id).first()
            if not user:
                log.error(f"User not found for public_id: {user_public_id}")
                raise HTTPException(status_code=404, detail="User not found")
            if not user.team:
                log.error(f"User {user_public_id} has no team associated")
                raise HTTPException(status_code=404, detail="User has no team")
            team = user.team
        
        log.info(f"Using team public_id: {team.public_id}")
        
        # Get team's Slack installation from team settings
        if not team.slack_settings or not isinstance(team.slack_settings, dict):
            log.error(f"No Slack settings found for team: {team.public_id}")
            raise HTTPException(status_code=404, detail="No Slack integration found for this team")
        
        slack_app_data = team.slack_settings.get("slack_app")
        if not slack_app_data or not isinstance(slack_app_data, dict):
            log.error(f"No Slack app installation found for team: {team.public_id}")
            raise HTTPException(status_code=404, detail="No Slack integration found for this team")
        
        bot_token = slack_app_data.get('bot_token')
        if not bot_token:
            log.error(f"No bot token found in Slack installation for team: {team.public_id}")
            raise HTTPException(status_code=404, detail="Slack integration is incomplete")
        
        log.info(f"Found Slack installation, bot_token exists: {bool(bot_token)}")
        
        # Initialize Slack client with bot token
        slack_client = WebClient(token=bot_token)
        log.info("Initialized Slack WebClient")
        
        # Fetch public channels
        log.info("Calling Slack conversations_list API")
        response = slack_client.conversations_list(
            types="public_channel",
            exclude_archived=True,
            limit=50  # Reasonable limit for search results
        )
        
        log.info(f"Slack API response ok: {response.get('ok', False)}")
        
        if not response["ok"]:
            error_msg = response.get('error', 'Unknown error')
            log.error(f"Slack API error: {error_msg}")
            raise HTTPException(status_code=500, detail=f"Failed to fetch channels from Slack: {error_msg}")
        
        # Filter channels by search query (case-insensitive)
        channels = response["channels"]
        log.info(f"Retrieved {len(channels)} channels from Slack")
        
        query_lower = query.lower()
        
        matching_channels = [
            {
                "id": channel["id"],
                "name": channel["name"]
            }
            for channel in channels
            if query_lower in channel["name"].lower()
        ]
        
        log.info(f"Found {len(matching_channels)} matching channels")
        
        # Sort by relevance (exact matches first, then alphabetical)
        matching_channels.sort(key=lambda ch: (
            not ch["name"].lower().startswith(query_lower),  # Exact matches first
            ch["name"].lower()  # Then alphabetical
        ))
        
        # Limit results to prevent overwhelming UI
        result = matching_channels[:20]
        log.info(f"Returning {len(result)} channels")
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        log.error(f"Error searching Slack channels: {str(e)}")
        log.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Internal server error while searching channels")


@router.post("/channels")
async def create_slack_channel(
    name: str = Query(..., min_length=1, description="Channel name to create (may include #)"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a public Slack channel in the team's connected workspace.
    If the channel already exists (name_taken), return the existing channel id and name.
    """
    log = new_logger("create_slack_channel")
    log.info(f"Creating Slack channel with requested name: '{name}'")
    try:
        # Normalize channel name for Slack API (no leading '#', lowercase)
        raw_name = (name or "").strip()
        channel_name = raw_name[1:] if raw_name.startswith('#') else raw_name
        channel_name = channel_name.lower()
        if not channel_name:
            raise HTTPException(status_code=400, detail="Invalid channel name")

        # Resolve team context similar to search endpoint
        user_public_id = current_user.get('public_id')
        user_role = current_user.get('role')
        user_team_public_id = current_user.get('team_id')

        from models.team import Team
        if user_role == 'PRE_SIGNUP':
            team = db.query(Team).filter_by(public_id=user_team_public_id).first()
            if not team:
                log.error(f"Team not found for public_id: {user_team_public_id}")
                raise HTTPException(status_code=404, detail="Team not found")
        else:
            user = db.query(WelcomepageUser).filter_by(public_id=user_public_id).first()
            if not user:
                log.error(f"User not found for public_id: {user_public_id}")
                raise HTTPException(status_code=404, detail="User not found")
            if not user.team:
                log.error(f"User {user_public_id} has no team associated")
                raise HTTPException(status_code=404, detail="User has no team")
            team = user.team
        if not team.slack_settings or not isinstance(team.slack_settings, dict):
            log.error(f"No Slack settings found for team: {team.public_id}")
            raise HTTPException(status_code=404, detail="No Slack integration found for this team")

        slack_app_data = team.slack_settings.get("slack_app")
        if not slack_app_data or not isinstance(slack_app_data, dict):
            log.error(f"No Slack app installation found for team: {team.public_id}")
            raise HTTPException(status_code=404, detail="No Slack integration found for this team")

        bot_token = slack_app_data.get('bot_token')
        if not bot_token:
            log.error(f"No bot token found in Slack installation for team: {team.public_id}")
            raise HTTPException(status_code=404, detail="Slack integration is incomplete")

        slack_client = WebClient(token=bot_token)
        log.info(f"Calling Slack conversations_create for '{channel_name}'")

        try:
            resp = slack_client.conversations_create(name=channel_name)
            if not resp.get("ok"):
                err = resp.get("error", "unknown_error")
                log.error(f"conversations_create not ok: {err}")
                raise HTTPException(status_code=500, detail=f"Slack error: {err}")
            ch = resp["channel"]
            log.info(f"Channel created: id={ch.get('id')} name={ch.get('name')}")

            # Invite the installing user to the newly created channel, if we know their Slack user id
            invited_installer = False
            try:
                installer_slack_user_id = None
                # Only attempt invite for authenticated users we can resolve
                if user_role != 'PRE_SIGNUP':
                    installer_slack_user_id = user.slack_user_id if 'user' in locals() and user else None
                if installer_slack_user_id:
                    log.info(f"Inviting installer slack_user_id={installer_slack_user_id} to channel {ch.get('id')}")
                    invite_resp = slack_client.conversations_invite(channel=ch["id"], users=installer_slack_user_id)
                    if invite_resp.get("ok"):
                        invited_installer = True
                    else:
                        log.warning(f"conversations_invite not ok: {invite_resp.get('error', 'unknown_error')}")
                else:
                    log.info("Installer does not have a slack_user_id; skipping invite")
            except Exception as ie:
                log.warning(f"Failed to invite installer to new channel: {ie}")

            return {"id": ch["id"], "name": ch["name"], "invited_installer": invited_installer}
        except Exception as e:
            # Import here to avoid module-level dependency if unused in other flows
            try:
                from slack_sdk.errors import SlackApiError  # type: ignore
            except Exception:
                SlackApiError = Exception  # fallback typing

            if isinstance(e, SlackApiError):
                err_code = getattr(e, 'response', {}).get('error') if getattr(e, 'response', None) else None
                log.warning(f"SlackApiError on create: {getattr(e, 'response', {})}")
                if err_code == 'name_taken':
                    log.info("Channel name taken; attempting to find existing channel")
                    try:
                        list_resp = slack_client.conversations_list(types="public_channel", exclude_archived=True, limit=1000)
                        channels = list_resp.get("channels", [])
                        for ch in channels:
                            if ch.get('name', '').lower() == channel_name and not ch.get('is_archived', False):
                                log.info(f"Found existing channel: id={ch.get('id')}")
                                # Do not auto-invite for existing channels in name_taken path
                                return {"id": ch["id"], "name": ch["name"], "invited_installer": False}
                        log.error("Channel reported as taken but not found in list")
                        raise HTTPException(status_code=409, detail="Channel name already taken")
                    except Exception as le:
                        log.error(f"Failed to list channels after name_taken: {str(le)}")
                        raise HTTPException(status_code=500, detail="Failed to resolve existing channel after name_taken")

            log.error(f"Failed to create channel: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to create Slack channel")

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Unexpected error creating channel: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error while creating channel")


@router.post("/channels/can-post")
async def can_post_to_channel(
    channel_id: Optional[str] = Body(None),
    name: Optional[str] = Body(None),
    send_test_message: bool = Body(True),
    auto_join: bool = Body(False),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Verify whether the bot can post to the specified channel.
    Accepts either channel_id or name. If name is provided, searches public channels.
    Options:
      - auto_join: attempt to join the channel if not a member (public channels only)
      - send_test_message: if True and bot is a member, send a lightweight test message
    Returns booleans and details about the checks performed.
    """
    log = new_logger("can_post_to_channel")
    log.info(f"Checking channel permissions for channel_id={channel_id}, name={name} (send_test_message={send_test_message}, auto_join={auto_join})")
    try:
        if not channel_id and not name:
            raise HTTPException(status_code=400, detail="Provide either channel_id or name")

        # Normalize name if provided
        resolved_name = None
        if name:
            raw = name.strip()
            resolved_name = (raw[1:] if raw.startswith('#') else raw).lower()

        # Get user's team
        user_team_id = current_user.get("team_id")
        if not user_team_id:
            raise HTTPException(status_code=400, detail="User team not found")

        # If only name was passed, resolve channel id by listing
        if not channel_id and resolved_name:
            # Use Slack client to resolve
            team = db.query(Team).filter_by(public_id=user_team_id).first()
            if not team:
                raise HTTPException(status_code=404, detail="Team not found")
            slack_settings = team.slack_settings or {}
            slack_app_data = slack_settings.get("slack_app") or {}
            bot_token = slack_app_data.get('bot_token')
            if not bot_token:
                raise HTTPException(status_code=400, detail="Slack integration not configured")
            client = WebClient(token=bot_token)

            try:
                log.info(f"Resolving channel by name: {resolved_name}")
                cursor = None
                found = None
                while True:
                    resp = client.conversations_list(types="public_channel,private_channel", limit=200, cursor=cursor)
                    if not resp.get("ok"):
                        raise Exception(resp.get('error', 'unknown_error'))
                    channels = resp.get("channels", [])
                    for ch in channels:
                        if ch.get("name", "").lower() == resolved_name:
                            found = ch
                            break
                    cursor = resp.get("response_metadata", {}).get("next_cursor")
                    if found or not cursor:
                        break
                if not found:
                    raise HTTPException(status_code=404, detail="Channel not found")
                channel_id = found.get("id")
            except HTTPException:
                raise
            except Exception as e:
                log.error(f"Failed to resolve channel by name: {e}")
                raise HTTPException(status_code=500, detail="Failed to resolve channel by name")

        # Delegate to service for verification and (optional) posting
        service_result = SlackPublishService.test_channel_connection(
            user_team_id,
            channel_id,
            auto_join=auto_join,
            send_test_message=send_test_message,
            db=db,
        )

        # Also include resolved channel_name (if we had one by name lookup and service couldn't fetch it)
        if resolved_name and not service_result.get("channel_name"):
            service_result["channel_name"] = resolved_name

        return service_result

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error in can_post_to_channel: {e}")
        raise HTTPException(status_code=500, detail="Internal server error while verifying Slack channel")


@router.post("/commands")
async def handle_slack_command(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Handle Slack slash commands
    This endpoint receives slash command requests from Slack (e.g., /welcomepage)
    """
    log = new_logger("handle_slack_command")
    try:
        # Get request body for signature verification
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
        
        # Parse form data manually (Slack sends slash commands as form-urlencoded)
        # Body is already consumed, so parse from bytes
        body_str = body.decode('utf-8')
        parsed_data = parse_qs(body_str, keep_blank_values=True)
        
        # Extract values (parse_qs returns lists, get first element)
        command = parsed_data.get("command", [None])[0]
        command_text = parsed_data.get("text", [""])[0] or ""
        team_id = parsed_data.get("team_id", [None])[0]  # Slack team_id
        user_id = parsed_data.get("user_id", [None])[0]  # Slack user_id of the person running the command
        
        log.info(f"Received Slack command: {command}, text: {command_text}, team_id: {team_id}, user_id: {user_id}")
        
        # Handle /welcomepage command
        if command == "/welcomepage":
            return await handle_welcomepage_command(
                command_text=command_text,
                slack_team_id=team_id,
                db=db
            )
        
        log.error(f"Unrecognized command: {command}")
        return JSONResponse(
            status_code=200,
            content={
                "response_type": "ephemeral",
                "text": f"Unrecognized command '{command}'"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to handle Slack command: {str(e)}", exc_info=True)
        # Return 200 to prevent Slack from retrying
        return JSONResponse(
            status_code=200,
            content={
                "response_type": "ephemeral",
                "text": "Oops! Something went wrong while processing your /welcomepage command. Please try again or reach out if the issue persists."
            }
        )


async def handle_welcomepage_command(
    command_text: str,
    slack_team_id: str,
    db: Session
) -> JSONResponse:
    """
    Handle the /welcomepage slash command
    Parses @teammember mentions and returns their welcomepage link
    """
    log = new_logger("handle_welcomepage_command")
    log.info(f"Handling /welcomepage command for team {slack_team_id}, text: {command_text}")
    
    # Check if the user asked for help
    if command_text.lower() == "help":
        log.info("User requested help for /welcomepage command")
        return JSONResponse(
            status_code=200,
            content={
                "response_type": "ephemeral",
                "text": "Usage: /welcomepage @teammember — Get a quick link to a team member's profile."
            }
        )
    
    # Parse the command text to extract Slack user ID and display name
    # Format: <@U123456|Display Name>
    user_id_match = re.search(r'<@([A-Z0-9]+)\|', command_text)
    display_name_match = re.search(r"\|([^>]+)>", command_text)
    
    if not user_id_match or not display_name_match:
        log.error(f"Could not parse command text: {command_text}")
        return JSONResponse(
            status_code=200,
            content={
                "response_type": "ephemeral",
                "text": "Sorry, I didn't recognize that command format. Please try using /welcomepage @teammember."
            }
        )
    
    command_user_id = user_id_match.group(1)  # Slack user ID of the mentioned user
    display_name = display_name_match.group(1)
    log.info(f"Parsed user_id: {command_user_id}, display_name: {display_name}")
    
    # Look up user by slack_user_id directly
    user = db.query(WelcomepageUser).filter_by(
        slack_user_id=command_user_id
    ).first()
    
    if not user:
        log.info(f"User not found - slack_user_id: {command_user_id}")
        blocks = SlackBlocksService.user_not_found_blocks(display_name=display_name)
        return JSONResponse(
            status_code=200,
            content={
                "response_type": "ephemeral",
                "text": "User not found",
                "blocks": blocks
            }
        )
    
    # User found - get team for team_data
    team = user.team
    
    # Build user data dict for blocks
    log.info(f"User wave_gif_url: {user.wave_gif_url}")
    user_data = {
        "name": user.name,
        "role": user.role,
        "location": user.location,
        "public_id": user.public_id,
        "wave_gif_url": user.wave_gif_url
    }
    
    # Build team data dict
    team_data = {
        "name": team.organization_name if team and team.organization_name else "Team"
    }
    
    blocks = SlackBlocksService.user_found_blocks(user_data=user_data, team_data=team_data)
    log.info(f"User found - slack_user_id: {command_user_id}, public_id: {user.public_id}")
    log.info(f"Generated blocks for slash command: {json.dumps(blocks, indent=2)}")
    
    return JSONResponse(
        status_code=200,
        content={
            "response_type": "ephemeral",
            "text": "Here is your teammate's Welcomepage",
            "blocks": blocks
        }
    )


