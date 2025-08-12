from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from models.team import Team
from models.welcomepage_user import WelcomepageUser
from services.slack_installation_service import SlackInstallationService
from schemas.slack import SlackInstallationData
from utils.logger_factory import new_logger
from services.slack_blocks_service import SlackBlocksService
import os


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
                
                # Update slack_settings to mark as uninstalled
                if team.slack_settings and team.slack_settings.get("slack_app"):
                    # existing_settings = team.slack_settings.copy()
                    # slack_app_data = existing_settings.get("slack_app", {})
                    # slack_app_data["uninstalled_at"] = datetime.utcnow().isoformat()
                    # slack_app_data["is_installed"] = False
                    # existing_settings["slack_app"] = slack_app_data
                    # team.slack_settings = existing_settings
                    # self.db.commit()
                    
                    log.info(f"Marked Slack app as uninstalled for team {team.public_id}")
                else:
                    log.warning(f"No slack_app data found for team {team.public_id}")
            else:
                log.warning(f"Team not found for Slack team_id: {team_id}")
            
            return {"status": "ok"}
            
        except Exception as e:
            log.error(f"Error handling app_uninstalled event: {str(e)}")
            self.db.rollback()
            return {"status": "error", "message": str(e)}
    
    def _handle_team_join(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle team join event (new user joins Slack workspace)"""
        log = new_logger("team_join")
        log.info("Handling team join event")
        
        try:
            event_data = payload.get("event", {})
            user_data = event_data.get("user", {})
            team_id = payload.get("team_id")
            
            # Check if user is a bot
            if user_data.get("is_bot", False):
                log.info("Bot user detected, no action taken")
                return {"status": "ignored", "message": "Bot user ignored"}
            
            # Find team and check auto-invite setting
            team = self._find_team_by_slack_team_id(team_id)
            if not team:
                log.warning(f"Team not found for Slack team_id: {team_id}")
                return {"status": "error", "message": "Team not found"}
            
            # Check if auto-invite is enabled
            auto_invite = team.slack_settings.get("auto_invite_users", False) if team.slack_settings else False
            if not auto_invite:
                log.info("Auto-invite disabled for this team")
                return {"status": "ignored", "message": "Auto-invite disabled"}
            
            # TODO: Implement user invitation logic
            # This would involve:
            # 1. Creating a WelcomepageUser record
            # 2. Sending a Slack message to the new user
            # 3. Providing them with a signup link
            
            log.info(f"Would send invitation to user {user_data.get('id')} in team {team_id}")
            return {"status": "ok", "message": "Team join event processed"}
            
        except Exception as e:
            log.error(f"Error handling team_join event: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    def _handle_user_profile_changed(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle user profile changed event"""
        log = new_logger("user_profile_changed")
        log.info("Handling user profile changed event")
        
        try:
            event_data = payload.get("event", {})
            user_data = event_data.get("user", {})
            
            # Check if user is a bot
            if user_data.get("is_bot", False):
                log.info("Bot user detected, no action taken")
                return {"status": "ignored", "message": "Bot user ignored"}
            
            user_id = user_data.get("id")
            if not user_id:
                log.error("No user ID found in profile change event")
                return {"status": "error", "message": "No user ID found"}
            
            # TODO: Implement profile update logic
            # This would involve:
            # 1. Finding the WelcomepageUser by Slack user_id
            # 2. Updating their profile information
            # 3. Handling user deletion if deleted=true
            
            log.info(f"Would update profile for user {user_id}")
            return {"status": "ok", "message": "Profile change event processed"}
            
        except Exception as e:
            log.error(f"Error handling user_profile_changed event: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    def _handle_app_home_opened(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle app home opened event"""
        log = new_logger("app_home_opened")
        log.info("Handling app home opened event")
        
        try:
            # Extract event data
            event_data = payload.get("event", {})
            user_id = event_data.get("user")
            team_id = payload.get("team_id")
            
            if not user_id or not team_id:
                log.error("Missing user_id or team_id in app_home_opened event")
                return {"status": "error", "message": "Missing required fields"}
            
            log.info(f"Processing app home opened for user {user_id} in Slack team {team_id}")
            
            # Find the team by Slack team_id
            team = self._find_team_by_slack_team_id(team_id)
            if not team:
                log.error(f"No team found for Slack team_id: {team_id}")
                return {"status": "error", "message": "Team not found"}
            
            log.info(f"Found team {team.public_id} for Slack team {team_id}")
            
            # Get Slack installation data to create WebClient
            installation = self.installation_service.get_installation_for_team(team.public_id)
            if not installation or not installation.bot_token:
                log.error(f"No Slack installation found for team {team.public_id}")
                return {"status": "error", "message": "Slack installation not found"}
            
            # Create Slack WebClient
            client = WebClient(token=installation.bot_token)
            
            # Get user profile from Slack
            try:
                slack_user_profile = client.users_profile_get(user=user_id)
                slack_user_info = client.users_info(user=user_id)
                
                slack_profile_data = slack_user_profile.get("profile", {})
                slack_user_data = slack_user_info.get("user", {})
                
                display_name = slack_profile_data.get("display_name") or slack_profile_data.get("real_name") or slack_user_data.get("name", "User")
                real_name = slack_profile_data.get("real_name", display_name)
                
                log.info(f"Retrieved Slack profile for user {user_id}: {display_name}")
                
            except SlackApiError as e:
                log.error(f"Failed to get Slack user profile: {e}")
                display_name = "User"
                real_name = "User"
            
            # Look up existing user by slack_user_id
            existing_user = self.db.query(WelcomepageUser).filter(
                WelcomepageUser.slack_user_id == user_id,
                WelcomepageUser.team_id == team.id
            ).first()
            
            # Determine user state and generate appropriate view
            is_new_user = existing_user is None
            has_published_page = False
            signup_url = ""
            
            wp_webapp_url = os.getenv('WEBAPP_URL')
            
            if existing_user:
                log.info(f"Found existing user {existing_user.public_id} for Slack user {user_id}")
                has_published_page = not existing_user.is_draft
                
                # Generate signup/signin URL based on user state
                if existing_user.auth_email:
                    # User has completed auth, send them to signin
                    signup_url = f"{wp_webapp_url}/auth"
                else:
                    # User exists but hasn't completed auth, send them to join flow
                    signup_url = f"{wp_webapp_url}/join/{team.public_id}"
            else:
                log.info(f"No existing user found for Slack user {user_id}, will show new user flow")
                
                # Check if team has auto-invite enabled
                auto_invite = False
                if team.slack_settings:
                    auto_invite = team.slack_settings.get("auto_invite_new_members", False)
                
                if auto_invite:
                    # Create a new user record for this Slack user
                    try:
                        new_user = WelcomepageUser(
                            name=real_name,
                            role="Team Member",  # Default role
                            location="Unknown",  # Default location
                            greeting="Hello!",  # Default greeting
                            selected_prompts=[],  # Empty prompts
                            answers={},  # Empty answers
                            team_id=team.id,
                            slack_user_id=user_id,
                            auth_role="PRE_SIGNUP",  # Pre-signup state
                            is_draft=True  # Draft state
                        )
                        
                        self.db.add(new_user)
                        self.db.commit()
                        
                        log.info(f"Created new user {new_user.public_id} for Slack user {user_id}")
                        existing_user = new_user
                        
                    except Exception as e:
                        log.error(f"Failed to create new user for Slack user {user_id}: {str(e)}")
                        self.db.rollback()
                
                # Generate signup URL for new users
                signup_url = f"{wp_webapp_url}/join/{team.public_id}"
            
            # Generate app home view blocks
            view = SlackBlocksService.app_home_page_blocks(
                signup_url=signup_url,
                has_published_page=has_published_page,
                is_new_user=is_new_user,
                organization_name=team.organization_name
            )
            
            log.info(f"Generated app home view for user {user_id}")
            log.debug(f"App home view blocks: {view}")
            
            # Publish the view to Slack
            try:
                response = client.views_publish(
                    user_id=user_id,
                    view=view
                )
                
                if response.get("ok"):
                    log.info(f"Successfully published app home view for user {user_id}")
                    return {"status": "ok", "message": "App home view published successfully"}
                else:
                    log.error(f"Failed to publish app home view: {response}")
                    return {"status": "error", "message": "Failed to publish view"}
                    
            except SlackApiError as e:
                log.error(f"Slack API error publishing app home view: {e}")
                return {"status": "error", "message": f"Slack API error: {e.response['error']}"}
            
        except Exception as e:
            log.error(f"Error handling app_home_opened event: {str(e)}")
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
