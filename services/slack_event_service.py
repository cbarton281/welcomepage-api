import json
import os
from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from models.team import Team
from models.welcomepage_user import WelcomepageUser
from services.slack_installation_service import SlackInstallationService
from schemas.slack import SlackInstallationData
from utils.logger_factory import new_logger


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
            log.info(f"Found team {team.public_id} for Slack team {team_id}")
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
            event_data = payload.get("event", {})
            user_id = event_data.get("user")
            team_id = payload.get("team_id")
            
            if not user_id or not team_id:
                log.error("Missing user_id or team_id in app_home_opened event")
                return {"status": "error", "message": "Missing required fields"}
            
            # TODO: Implement app home view logic
            # This would involve:
            # 1. Getting Slack installation data
            # 2. Creating/updating app home view
            # 3. Publishing view to Slack
            
            log.info(f"Would update app home for user {user_id} in team {team_id}")
            return {"status": "ok", "message": "App home opened event processed"}
            
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
