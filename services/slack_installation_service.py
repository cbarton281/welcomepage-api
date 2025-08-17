import json
import os
from typing import Optional, Dict, Any
from datetime import datetime
from urllib.parse import urlencode

from typing import Dict, Any, Optional
from urllib.parse import urlencode
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.exc import OperationalError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log
from slack_sdk.errors import SlackApiError
from slack_sdk import WebClient
import logging
from models.team import Team
from models.slack_state_store import SlackStateStore
from models.welcomepage_user import WelcomepageUser
from schemas.slack import SlackOAuthStartResponse, SlackInstallationResponse, SlackInstallationData
from utils.slack_state_manager import SlackStateManager
from utils.logger_factory import new_logger
import os
import requests

# Create retry loggers
installation_retry_logger = new_logger("slack_installation_retry")
user_update_retry_logger = new_logger("slack_user_update_retry")
uninstall_retry_logger = new_logger("slack_uninstall_retry")

class SlackInstallationService:
    """Service for handling Slack OAuth installation flow"""
    
    def __init__(self, db: Session):
        self.db = db
        self.state_manager = SlackStateManager(db)
        
        # Load Slack credentials from environment
        self.client_id = os.getenv("SLACK_CLIENT_ID")
        self.client_secret = os.getenv("SLACK_CLIENT_SECRET")
        
        if not self.client_id or not self.client_secret:
            raise ValueError("SLACK_CLIENT_ID and SLACK_CLIENT_SECRET environment variables must be set")
    
    def start_oauth_flow(self, team_public_id: str) -> SlackOAuthStartResponse:
        """Start the Slack OAuth flow by generating authorization URL"""
        log = new_logger("start_oauth_flow")
        try:
            # Generate and store state with team_public_id encoded
            state = self.state_manager.issue_state(team_public_id=team_public_id)
            
            # Build OAuth parameters
            params = {
                "client_id": self.client_id,
                "scope": "channels:join,channels:manage,channels:read,chat:write,commands,im:write,users.profile:read,users:read",
                "user_scope": "users.profile:write,users:read",
                "state": state
            }
            
            authorize_url = f"https://slack.com/oauth/v2/authorize?{urlencode(params)}"
            
            log.info(f"Generated OAuth URL for team {team_public_id}, state: {state}")
            
            return SlackOAuthStartResponse(
                authorize_url=authorize_url,
                state=state
            )
            
        except Exception as e:
            log.error(f"Failed to start OAuth flow for team {team_public_id}: {str(e)}")
            raise
    
    def handle_oauth_callback(self, code: str, state: str) -> SlackInstallationResponse:
        """Handle OAuth callback and complete installation"""
        log = new_logger("handle_oauth_callback")
        try:
            # Get team_public_id from state before consuming it
            team_public_id = self.state_manager.get_team_public_id_from_state(state)
            if not team_public_id:
                raise ValueError("Invalid or expired OAuth state - could not retrieve team ID")
            
            # Validate and consume state
            if not self.state_manager.consume_state(state):
                raise ValueError("Invalid or expired OAuth state")
            
            # Exchange code for tokens
            client = WebClient()
            oauth_response = client.oauth_v2_access(
                client_id=self.client_id,
                client_secret=self.client_secret,
                code=code
            )
            
            log.info(f"OAuth response received for team {team_public_id}: {json.dumps(oauth_response.data, indent=2)}")
            
            # Extract installation data
            installation_data = self._extract_installation_data(oauth_response)
            
            # Get bot_id if we have a bot token
            if installation_data.bot_token:
                try:
                    auth_test = client.auth_test(token=installation_data.bot_token)
                    installation_data.bot_id = auth_test.get("bot_id")
                except SlackApiError as e:
                    log.warning(f"Failed to get bot_id: {e}")
            
            # Save installation to team
            self._save_installation_to_team(team_public_id, installation_data)
            
            # Update installer user's Slack user ID
            self._update_user_slack_id(team_public_id, installation_data.user_id)
            
            return SlackInstallationResponse(
                success=True,
                message="Slack installation completed successfully",
                team_id=installation_data.team_id,
                team_name=installation_data.team_name,
                enterprise_id=installation_data.enterprise_id,
                enterprise_name=installation_data.enterprise_name
            )
            
        except Exception as e:
            log.error(f"OAuth callback failed: {str(e)}")
            
            # Revoke tokens if installation failed
            if 'oauth_response' in locals():
                self._revoke_tokens(oauth_response)
            
            raise
    
    def _extract_installation_data(self, oauth_response) -> SlackInstallationData:
        """Extract installation data from OAuth response"""
        installed_enterprise = oauth_response.get("enterprise", {}) or {}
        installed_team = oauth_response.get("team", {}) or {}
        installer = oauth_response.get("authed_user", {}) or {}
        incoming_webhook = oauth_response.get("incoming_webhook", {}) or {}
        
        return SlackInstallationData(
            app_id=oauth_response.get("app_id"),
            enterprise_id=installed_enterprise.get("id"),
            enterprise_name=installed_enterprise.get("name"),
            enterprise_url=installed_enterprise.get("url"),
            team_id=installed_team.get("id"),
            team_name=installed_team.get("name"),
            bot_token=oauth_response.get("access_token"),
            bot_user_id=oauth_response.get("bot_user_id"),
            bot_scopes=oauth_response.get("scope"),
            user_id=installer.get("id"),
            user_token=installer.get("access_token"),
            user_scopes=installer.get("scope"),
            incoming_webhook_url=incoming_webhook.get("url"),
            incoming_webhook_channel=incoming_webhook.get("channel"),
            incoming_webhook_channel_id=incoming_webhook.get("channel_id"),
            incoming_webhook_configuration_url=incoming_webhook.get("configuration_url"),
            is_enterprise_install=oauth_response.get("is_enterprise_install", False),
            token_type=oauth_response.get("token_type"),
            installed_at=datetime.utcnow(),
            installer_user_id=installer.get("id")
        )
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(OperationalError),
        before_sleep=before_sleep_log(installation_retry_logger, logging.WARNING)
    )
    def _save_installation_to_team(self, team_identifier: str, installation_data: SlackInstallationData):
        """Save Slack installation data to team's slack_settings"""
        log = new_logger("save_installation_to_team")
        log.info(f"Saving Slack installation for team {team_identifier}")   
        try:
            # Try to find team by ID first (for hardcoded team_id=1), then by public_id
            team = None
            if team_identifier.isdigit():
                team = self.db.query(Team).filter_by(id=int(team_identifier)).first()
            else:
                team = self.db.query(Team).filter_by(public_id=team_identifier).first()
            
            if not team:
                raise ValueError(f"Team not found: {team_identifier}")
            
            log.info(f"Found team {team.public_id} for Slack team {team_identifier}")
            # Get existing slack_settings or initialize empty dict
            existing_settings = team.slack_settings or {}
            log.info(f"Existing slack_settings: {existing_settings}")
            
            # Convert installation data to dict for JSON storage
            slack_app_data = installation_data.model_dump()
            log.info(f"Installation data: {slack_app_data}")
            
            # Convert datetime to ISO string for JSON serialization
            if slack_app_data.get("installed_at"):
                slack_app_data["installed_at"] = slack_app_data["installed_at"].isoformat()
            
            log.info(f"Installation data after conversion: {slack_app_data}")
            
            # Preserve existing settings and nest Slack app data under 'slack_app' property
            existing_settings["slack_app"] = slack_app_data
            
            # Set auto_invite_users to true when Slack installation is performed
            existing_settings["auto_invite_users"] = True
            
            log.info(f"Updated slack_settings: {existing_settings}")
            
            # Create a new dict to ensure SQLAlchemy detects the change
            team.slack_settings = dict(existing_settings)
            log.info(f"New slack_settings: {team.slack_settings}")
            
            # Explicitly mark the field as modified for SQLAlchemy
            flag_modified(team, 'slack_settings')
            log.info(f"Marked slack_settings as modified")
            
            self.db.commit()
            log.info(f"Committed transaction")
            
            log.info(f"Saved Slack installation for team {team_identifier} (Slack team: {installation_data.team_name})")
            log.info(f"Updated slack_settings: {team.slack_settings}")
            
        except Exception as e:
            log.error(f"Failed to save installation to team {team_identifier}: {str(e)}")
            self.db.rollback()
            raise
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(OperationalError),
        before_sleep=before_sleep_log(user_update_retry_logger, logging.WARNING)
    )
    def _update_user_slack_id(self, team_identifier: str, slack_user_id: str):
        """Update user's Slack ID"""
        log = new_logger("update_user_slack_id")
        try:
            # Try to find team by ID first (for hardcoded team_id=1), then by public_id
            team = None
            if team_identifier.isdigit():
                team = self.db.query(Team).filter_by(id=int(team_identifier)).first()
            else:
                team = self.db.query(Team).filter_by(public_id=team_identifier).first()
            
            if not team:
                raise ValueError(f"Team not found: {team_identifier}")
            
            log.info(f"Found team {team.public_id} for Slack team {team_identifier}")
            
            # Update user's Slack ID
            user = self.db.query(WelcomepageUser).filter_by(team_id=team.id).first()
            if user:
                user.slack_user_id = slack_user_id
                self.db.commit()
                log.info(f"Updated user's Slack ID for team {team_identifier}")
            else:
                log.warning(f"No user found for team {team_identifier}")
                
        except Exception as e:
            log.error(f"Failed to update user's Slack ID for team {team_identifier}: {str(e)}")
            self.db.rollback()
            raise
    
    def _revoke_tokens(self, oauth_response):
        """Revoke tokens if installation fails"""
        log = new_logger("revoke_tokens")
        try:
            bot_token = oauth_response.get("access_token")
            user_token = oauth_response.get("authed_user", {}).get("access_token")
            
            if bot_token:
                self._revoke_token(bot_token)
            
            if user_token:
                self._revoke_token(user_token)
                
        except Exception as e:
            log.error(f"Failed to revoke tokens: {str(e)}")
    
    def _revoke_token(self, token: str):
        """Revoke a specific token"""
        log = new_logger("revoke_token")
        try:
            client = WebClient(token=token)
            response = client.auth_revoke()
            
            if response.get("revoked"):
                log.info("Token successfully revoked")
            else:
                log.warning("Token revocation was unsuccessful")
                
        except SlackApiError as e:
            log.error(f"Slack API error during token revocation: {e.response['error']}")
        except Exception as e:
            log.error(f"Unexpected error during token revocation: {e}")
    
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(OperationalError),
        before_sleep=before_sleep_log(uninstall_retry_logger, logging.WARNING)
    )
    def uninstall_slack(self, team_identifier: str) -> bool:
        """Remove Slack installation from team"""
        log = new_logger("uninstall_slack")
        try:
            # Try to find team by ID first (for hardcoded team_id=1), then by public_id
            team = None
            if team_identifier.isdigit():
                team = self.db.query(Team).filter_by(id=int(team_identifier)).first()
            else:
                team = self.db.query(Team).filter_by(public_id=team_identifier).first()
            
            if not team:
                raise ValueError(f"Team not found: {team_identifier}")
            
            # Get installation data before removing it
            installation_data = None
            if team.slack_settings and team.slack_settings.get("slack_app"):
                installation_data = SlackInstallationData(**team.slack_settings.get("slack_app"))
            
            if not installation_data:
                log.warning(f"No Slack installation found for team {team_identifier}")
                return True  # Already uninstalled
            
            # Call Slack apps.uninstall API to uninstall from Slack workspace
            try:
                if installation_data.bot_token:
                    client = WebClient(token=installation_data.bot_token)
                    uninstall_response = client.apps_uninstall(
                        client_id=self.client_id,
                        client_secret=self.client_secret
                    )
                    
                    if uninstall_response.get("ok"):
                        log.info(f"Successfully uninstalled app from Slack workspace for team {team_identifier}")
                    else:
                        log.warning(f"Slack apps.uninstall API returned error: {uninstall_response.get('error', 'Unknown error')}")
                        # Continue with local cleanup even if Slack API fails
                else:
                    log.warning(f"No bot token found for team {team_identifier}, skipping Slack API uninstall")
                    
            except SlackApiError as e:
                log.error(f"Slack API error during uninstall for team {team_identifier}: {e.response.get('error', str(e))}")
                # Continue with local cleanup even if Slack API fails
            except Exception as e:
                log.error(f"Unexpected error calling Slack apps.uninstall for team {team_identifier}: {str(e)}")
                # Continue with local cleanup even if Slack API fails
            
            # Revoke tokens after uninstalling from Slack
            if installation_data.bot_token:
                self._revoke_token(installation_data.bot_token)
            if installation_data.user_token:
                self._revoke_token(installation_data.user_token)
            
            # Preserve other slack_settings but remove slack_app data and auto_invite_users
            if team.slack_settings:
                existing_settings = team.slack_settings.copy()
                existing_settings.pop("slack_app", None)  # Remove slack_app data
                existing_settings.pop("auto_invite_users", None)  # Remove auto_invite_users setting
                team.slack_settings = existing_settings if existing_settings else None
            else:
                team.slack_settings = None
            
            # Mark the database field as modified for SQLAlchemy
            flag_modified(team, "slack_settings")
            self.db.commit()
            
            log.info(f"Uninstalled Slack for team {team_identifier}")
            return True
            
        except Exception as e:
            log.error(f"Failed to uninstall Slack for team {team_identifier}: {str(e)}")
            self.db.rollback()
            return False

    def check_custom_profile_field(self, team_identifier: str) -> bool:
        """Check if the custom 'Welcomepage' profile field is configured in Slack workspace"""
        log = new_logger("check_custom_profile_field")
        log.info(f"Checking custom profile field for team {team_identifier}")
        try:
            # Get team data
            team = None
            if team_identifier.isdigit():
                team = self.db.query(Team).filter_by(id=int(team_identifier)).first()
            else:
                team = self.db.query(Team).filter_by(public_id=team_identifier).first()
            
            if not team or not team.slack_settings:
                log.warning(f"No team or Slack settings found for team {team_identifier}")
                return False
            
            # Get Slack installation from team settings
            slack_app_data = team.slack_settings.get("slack_app")
            if not slack_app_data or not isinstance(slack_app_data, dict):
                log.warning(f"No Slack app installation found for team {team_identifier}")
                return False
            
            bot_token = slack_app_data.get('bot_token')
            if not bot_token:
                log.warning(f"No bot token found for team {team_identifier}")
                return False
            
            # Use bot token to check for custom profile fields
            client = WebClient(token=bot_token)
            
            # Call team.profile.get to get custom profile fields
            response = client.team_profile_get()
            
            if not response.get("ok"):
                log.error(f"Slack API error: {response.get('error', 'Unknown error')}")
                return False
            
            # Check if 'Welcomepage' field exists in custom fields
            profile = response.get("profile", {})
            fields = profile.get("fields", [])
            
            for field in fields:
                log.info(f"Checking field: {field}")
                if field.get("label", "").lower() == "welcomepage":
                    log.info(f"Found Welcomepage custom profile field for team {team_identifier}")
                    return True
            
            log.info(f"Welcomepage custom profile field not found for team {team_identifier}")
            return False
            
        except SlackApiError as e:
            log.error(f"Slack API error checking custom profile field for team {team_identifier}: {e.response['error']}")
            return False
        except Exception as e:
            log.error(f"Failed to check custom profile field for team {team_identifier}: {str(e)}")
            return False
