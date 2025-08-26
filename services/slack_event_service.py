from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log
import logging

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from models.team import Team
from models.welcomepage_user import WelcomepageUser
from services.slack_installation_service import SlackInstallationService
from schemas.slack import SlackInstallationData
from utils.logger_factory import new_logger
from services.slack_blocks_service import SlackBlocksService
import os
from urllib.parse import urlencode

# Create retry loggers
event_retry_logger = new_logger("slack_event_retry")
uninstall_event_retry_logger = new_logger("slack_uninstall_event_retry")
team_join_retry_logger = new_logger("slack_team_join_retry")


class SlackEventService:
    """Service for handling Slack event callbacks"""
    
    # Event type constants
    URL_VERIFICATION_EVENT = 'url_verification'
    TEAM_JOIN_EVENT = 'team_join'
    USER_PROFILE_CHANGED = 'user_profile_changed'
    EVENT_CALLBACK = 'event_callback'
    EVENT_APP_HOME_OPENED = 'app_home_opened'
    EVENT_APP_UNINSTALLED = 'app_uninstalled'
    
    def __init__(self, db: Session):
        self.db = db
        self.installation_service = SlackInstallationService(db)
        
    def handle_event(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Main event handler that routes to specific event handlers"""
        log = new_logger("slack_event_handler")
        
        try:
            event_type = payload.get("type")
            log.info(f"Processing Slack event type: {event_type}")
            
            # Handle URL verification challenge
            if event_type == self.URL_VERIFICATION_EVENT:
                return self._handle_url_verification(payload)
            
            # Handle event callbacks
            if event_type == self.EVENT_CALLBACK:
                event_data = payload.get("event", {})
                inner_event_type = event_data.get("type")
                
                if inner_event_type == self.EVENT_APP_UNINSTALLED:
                    return self._handle_app_uninstalled(payload)
                elif inner_event_type == self.TEAM_JOIN_EVENT:
                    return self._handle_team_join(payload)
                elif inner_event_type == self.USER_PROFILE_CHANGED:
                    return self._handle_user_profile_changed(payload)
                elif inner_event_type == self.EVENT_APP_HOME_OPENED:
                    return self._handle_app_home_opened(payload)
            
            log.info(f"Unhandled event type: {event_type}")
            return {"status": "ignored"}
            
        except Exception as e:
            log.error(f"Error handling Slack event: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    def _handle_url_verification(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle Slack URL verification challenge"""
        log = new_logger("url_verification")
        challenge = payload.get("challenge")
        
        if challenge:
            log.info("Responding to Slack URL verification challenge")
            return {"challenge": challenge}
        else:
            log.error("No challenge found in URL verification request")
            return {"status": "error", "message": "No challenge found"}
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(OperationalError),
        before_sleep=before_sleep_log(uninstall_event_retry_logger, logging.WARNING)
    )
    def _handle_app_uninstalled(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle app uninstalled event"""
        log = new_logger("app_uninstalled")
        log.info("Handling app uninstalled event")
        
        try:
            team_id = payload.get("team_id")
            if not team_id:
                log.error("No team_id found in app_uninstalled event")
                return {"status": "error", "message": "No team_id found"}
            
            log.info(f"Processing app uninstall for Slack team: {team_id}")
            
            # Find team by slack team_id in the slack_settings
            team = self._find_team_by_slack_team_id(team_id)
            if team:
                log.info(f"Found team {team.public_id} for Slack team {team_id}")
                
                # Remove Slack installation data when app is uninstalled from Slack
                if team.slack_settings and team.slack_settings.get("slack_app"):
                    log.info(f"Removing Slack installation data for team {team.public_id}")
                    # Delegate to installation service helper for consistent cleanup
                    self.installation_service._cleanup_slack_settings(team)
                    log.info(f"Successfully removed Slack installation data for team {team.public_id}")
                else:
                    log.warning(f"No slack_app data found for team {team.public_id}")
            else:
                log.warning(f"Team not found for Slack team_id: {team_id}")
            
            return {"status": "ok", "message": "App uninstall event processed successfully"}
            
        except OperationalError:
            # These exceptions are handled by the @retry decorator - let them bubble up
            raise
        except Exception as e:
            # Only catch non-retryable exceptions here
            log.error(f"Non-retryable error handling app_uninstalled event: {str(e)}")
            self.db.rollback()
            return {"status": "error", "message": str(e)}
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((OperationalError, SlackApiError)),
        before_sleep=before_sleep_log(team_join_retry_logger, logging.WARNING)
    )
    def _handle_team_join(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle team_join event when a new user joins the Slack workspace"""
        log = new_logger("team_join")
        log.info("Handling team_join event")
        
        try:
            event_data = payload.get("event", {})
            user_data = event_data.get("user", {})
            team_id = payload.get("team_id")
            user_id = user_data.get("id")
            
            log.info(f"Processing team_join for user {user_id} in Slack team {team_id}")
            log.info(f"User data: {user_data}")
            
            # Check if user is a bot
            if user_data.get("is_bot", False):
                log.info("Bot user detected, no action taken")
                return {"status": "ignored", "message": "Bot user ignored"}
            
            # Find team and check auto-invite setting
            team = self._find_team_by_slack_team_id(team_id)
            if not team:
                log.warning(f"Team not found for Slack team_id: {team_id}")
                return {"status": "error", "message": "Team not found"}
            
            log.info(f"Found team {team.public_id} for Slack team {team_id}")
            
            # Check if auto-invite is enabled
            auto_invite = team.slack_settings.get("auto_invite_users", False) if team.slack_settings else False
            if not auto_invite:
                log.info("Auto-invite disabled for this team")
                return {"status": "ignored", "message": "Auto-invite disabled"}
            
            # Get bot token from team's Slack settings
            slack_app_data = team.slack_settings.get("slack_app", {})
            bot_token = slack_app_data.get("bot_token")
            if not bot_token:
                log.error(f"No bot token found in Slack settings for team {team.public_id}")
                return {"status": "error", "message": "Slack bot token not found"}
            
            # Create Slack WebClient
            client = WebClient(token=bot_token)
            
            # Extract user information for the message
            profile = user_data.get("profile", {})
            user_name = profile.get("display_name") or profile.get("real_name") or user_data.get("real_name") or user_data.get("name", "User")
            company_name = team.organization_name 
            
            log.info(f"Sending welcome message to user {user_name} for company {company_name}")
            
            # Generate signup URL with Slack user info
            wp_webapp_url = os.getenv('WEBAPP_URL')
            slack_params = {
                'slack_user_id': user_id,
                'slack_name': user_name,
                'from': 'slack'
            }
            signup_url = f"{wp_webapp_url}/join/{team.public_id}?{urlencode(slack_params)}"
            
            # Generate message blocks
            blocks = SlackBlocksService.new_user_blocks(
                user_name=user_name,
                company_name=company_name,
                signup_url=signup_url
            )
            
            log.info(f"Generated welcome message blocks for user {user_id} {blocks}")
            
            # Open DM channel with the user
            try:
                dm_response = client.conversations_open(users=[user_id])
                if not dm_response.get("ok"):
                    log.error(f"Failed to open DM channel with user {user_id}: {dm_response}")
                    return {"status": "error", "message": "Failed to open DM channel"}
                
                channel_id = dm_response["channel"]["id"]
                log.info(f"Opened DM channel {channel_id} with user {user_id}")
                
            except SlackApiError as e:
                log.error(f"Slack API error opening DM channel: {e}")
                raise  # Let retry decorator handle this
            
            # Send welcome message
            try:
                message_response = client.chat_postMessage(
                    channel=channel_id,
                    blocks=blocks,
                    text=f"Welcome to {company_name}! Please create your Welcomepage."  # Fallback text
                )
                
                if message_response.get("ok"):
                    log.info(f"Successfully sent welcome message to user {user_id}")
                    log.info(f"Message response: {message_response}")
                    return {"status": "ok", "message": "Welcome message sent successfully"}
                else:
                    log.error(f"Failed to send welcome message: {message_response}")
                    return {"status": "error", "message": "Failed to send message"}
                    
            except SlackApiError as e:
                log.error(f"Slack API error sending message: {e}")
                raise  # Let retry decorator handle this
            
        except (OperationalError, SlackApiError):
            # These exceptions are handled by the @retry decorator - let them bubble up
            raise
        except Exception as e:
            # Only catch non-retryable exceptions here
            log.error(f"Non-retryable error handling team_join event: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    def _handle_user_profile_changed(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle user profile changed event"""
        log = new_logger("user_profile_changed")
        log.info("Handling user profile changed event")

        try:
            event_data = payload.get("event", {})
            user_data = event_data.get("user", {})
            team_id = payload.get("team_id")

            # Ignore bot users
            if user_data.get("is_bot", False):
                log.info("Bot user detected, no action taken")
                return {"status": "ignored", "message": "Bot user ignored"}

            slack_user_id = user_data.get("id") or event_data.get("user")
            if not slack_user_id:
                log.error("No user ID found in profile change event")
                return {"status": "error", "message": "No user ID found"}

            # We only care if the user is marked as deleted
            is_deleted = bool(user_data.get("deleted", False))
            if not is_deleted:
                log.info(f"User {slack_user_id} profile changed but not deleted; ignoring.")
                return {"status": "ignored", "message": "Non-deletion profile change ignored"}

            if not team_id:
                log.error("No team_id found in user_profile_changed event")
                return {"status": "error", "message": "No team_id found"}

            # Find the team by Slack team_id
            team = self._find_team_by_slack_team_id(team_id)
            if not team:
                log.warning(f"Team not found for Slack team_id: {team_id}")
                return {"status": "error", "message": "Team not found"}

            # Clear slack_user_id for the first matching user in this team (should be unique)
            user = self.db.query(WelcomepageUser).filter(
                WelcomepageUser.team_id == team.id,
                WelcomepageUser.slack_user_id == slack_user_id
            ).first()

            if not user:
                log.info(f"No WelcomepageUser found with slack_user_id {slack_user_id} in team {team.public_id}")
                return {"status": "ok", "message": "No matching user found; nothing to update"}

            user.slack_user_id = None

            try:
                self.db.commit()
                log.info(f"Cleared slack_user_id for user {user.public_id} in team {team.public_id} due to Slack deletion of {slack_user_id}")
            except Exception as commit_err:
                self.db.rollback()
                log.error(f"Failed to commit slack_user_id clearing for user {slack_user_id}: {str(commit_err)}")
                return {"status": "error", "message": "Database commit failed"}

            return {"status": "ok", "message": "Cleared slack_user_id for 1 user"}

        except Exception as e:
            # No @retry decorator on this method, so handle normally
            log.error(f"Error handling user_profile_changed event: {str(e)}")
            return {"status": "error", "message": str(e)}

    def _find_team_by_slack_team_id(self, slack_team_id: str) -> Optional[Team]:
        """Find a team by Slack team_id stored in slack_settings"""
        try:
            teams = self.db.query(Team).filter(Team.slack_settings.isnot(None)).all()
            
            for team in teams:
                slack_app_data = team.slack_settings.get("slack_app", {}) if team.slack_settings else {}
                if slack_app_data.get("team_id") == slack_team_id:
                    return team
            
            return None
            
        except Exception as e:
            log = new_logger("find_team_by_slack_team_id")
            log.error(f"Error finding team by Slack team_id {slack_team_id}: {str(e)}")
            return None
