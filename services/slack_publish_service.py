from typing import Dict, Any, Optional
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, IntegrityError, DataError, DatabaseError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log
import logging
from database import get_db
from models.welcomepage_user import WelcomepageUser
from models.team import Team
from services.slack_installation_service import SlackInstallationService
from services.slack_blocks_service import SlackBlocksService
from utils.logger_factory import new_logger
import os

# Create retry loggers
publish_retry_logger = new_logger("publish_welcomepage_retry")
test_channel_retry_logger = new_logger("test_channel_connection_retry")


class SlackPublishService:
    """Service for publishing welcomepage announcements to Slack"""
    
    @staticmethod
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((OperationalError, IntegrityError, DataError, DatabaseError, SlackApiError)),
        before_sleep=before_sleep_log(publish_retry_logger, logging.WARNING)
    )
    def publish_welcomepage(
        user_public_id: str, 
        custom_message: str = "",
        db: Session = None
    ) -> Dict[str, Any]:
        """
        Publish a user's welcomepage to their team's designated Slack channel
        
        Args:
            user_public_id: Public ID of the user whose welcomepage to publish
            custom_message: Optional custom message from the user
            db: Database session
            
        Returns:
            Dict containing success status, message timestamp, and any errors
        """
        log = new_logger(f"publish_welcomepage")
        log.info(f"user public id: {user_public_id}  custom message: {custom_message}")
        
        if not db:
            db = next(get_db())
        
        try:
            # Get user and team data
            user = db.query(WelcomepageUser).filter_by(public_id=user_public_id).first()
            if not user:
                log.error(f"User not found: {user_public_id}")
                return {
                    "success": False,
                    "error": "User not found",
                    "message": "The specified user could not be found"
                }
            log.info(f"user: {user.to_dict()}")

            team = user.team
            if not team:
                log.error(f"Team not found for user: {user_public_id}")
                return {
                    "success": False,
                    "error": "Team not found",
                    "message": "User's team could not be found"
                }
            log.info(f"team: {team.to_dict()}")
            
            # Get Slack installation and publish channel from team settings
            if not team.slack_settings or not isinstance(team.slack_settings, dict):
                log.error(f"No Slack settings found for team: {team.public_id}")
                return {
                    "success": False,
                    "error": "No Slack integration",
                    "message": "This team doesn't have Slack integration set up"
                }
            
            # Get Slack app installation data
            slack_app_data = team.slack_settings.get("slack_app")
            if not slack_app_data or not isinstance(slack_app_data, dict):
                log.error(f"No Slack app installation found for team: {team.public_id}")
                return {
                    "success": False,
                    "error": "No Slack integration",
                    "message": "This team doesn't have Slack integration set up"
                }
            
            # Verify required Slack installation fields
            bot_token = slack_app_data.get('bot_token')
            if not bot_token:
                log.error(f"No bot token found in Slack installation for team: {team.public_id}")
                return {
                    "success": False,
                    "error": "Invalid Slack integration",
                    "message": "Slack integration is incomplete"
                }
            
            # Get publish channel from team settings
            publish_channel_data = team.slack_settings.get('publish_channel')
            
            if not publish_channel_data:
                log.error(f"No publish channel configured for team: {team.public_id}")
                return {
                    "success": False,
                    "error": "No publish channel",
                    "message": "No Slack channel has been configured for publishing welcomepages"
                }
            
            # Expect channel object with id and name
            if not isinstance(publish_channel_data, dict):
                log.error(f"Invalid publish channel format for team: {team.public_id} - expected object with id and name")
                return {
                    "success": False,
                    "error": "Invalid channel configuration",
                    "message": "Channel configuration format is invalid"
                }
            
            channel_id = publish_channel_data.get('id')
            channel_name = publish_channel_data.get('name')
            
            if not channel_id:
                log.error(f"Channel object missing 'id' field for team: {team.public_id}")
                return {
                    "success": False,
                    "error": "Invalid channel configuration",
                    "message": "Channel configuration is missing required ID"
                }
            
            # Use channel ID for posting (more reliable)
            channel_to_post = channel_id
            channel_display_name = channel_name or channel_id
            
            # Prepare user data for block generation
            user_data = {
                "slack_user_id": user.slack_user_id,
                "name": user.name,
                "nickname": user.nickname,
                "role": user.role,
                "location": user.location,
                "public_id": user.public_id,
                "profile_photo_url": user.profile_photo_url,
                "wave_gif_url": user.wave_gif_url
            }
            
            team_data = {
                "public_id": team.public_id,
                "organization_name": team.organization_name
            }
            
            # Generate Slack message blocks
            blocks = SlackBlocksService.story_publish_blocks(
                user_data=user_data,
                team_data=team_data,
                custom_msg=custom_message
            )
            log.info(f"blocks {blocks}")
            log.info(f"custom_message [{custom_message}]")
            
            # Post to Slack
            client = WebClient(token=bot_token)
            
            log.info(f"Posting welcomepage to Slack channel: {channel_display_name} ({channel_to_post}) for user: {user.name}")
            
            response = client.chat_postMessage(
                channel=channel_to_post,
                blocks=blocks,
                text=f"Welcome {user.name}!"  # Fallback text for notifications
            )
            
            if response["ok"]:
                log.info(f"Successfully posted to Slack. Message timestamp: {response['ts']}")
                
                # Generate message URL if team domain is available
                message_url = None
                team_domain = slack_app_data.get('team_domain')
                if team_domain:
                    message_url = f"https://{team_domain}.slack.com/archives/{response['channel']}/p{response['ts'].replace('.', '')}"
                
                return {
                    "success": True,
                    "message": "Successfully posted to Slack",
                    "slack_response": {
                        "channel": response["channel"],
                        "timestamp": response["ts"],
                        "message_url": message_url
                    }
                }
            else:
                log.error(f"Slack API returned not ok: {response}")
                return {
                    "success": False,
                    "error": "Slack API error",
                    "message": "Failed to post message to Slack",
                    "slack_response": response
                }
                
        except SlackApiError as e:
            log.error(f"Slack API error: {e.response['error']}")
            error_msg = e.response.get('error', 'Unknown Slack error')
            
            # Provide user-friendly error messages
            if error_msg == 'channel_not_found':
                user_message = "The configured Slack channel could not be found. Please check your team's Slack settings."
            elif error_msg == 'not_in_channel':
                user_message = "The Welcomepage bot is not in the configured channel. Please invite the bot to the channel."
            elif error_msg == 'access_denied':
                user_message = "Access denied. The bot may not have permission to post in the configured channel."
            else:
                user_message = f"Slack error: {error_msg}"
            
            return {
                "success": False,
                "error": "Slack API error",
                "message": user_message,
                "slack_error": error_msg
            }
            
        except (OperationalError, IntegrityError, DataError, DatabaseError, SlackApiError):
            # These exceptions are handled by the @retry decorator - let them bubble up
            raise
        except Exception as e:
            # Only catch non-retryable exceptions here
            log.error(f"Non-retryable error publishing to Slack: {str(e)}")
            return {
                "success": False,
                "error": "Internal error",
                "message": "An unexpected error occurred while posting to Slack"
            }
    
    @staticmethod
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((OperationalError, IntegrityError, DataError, DatabaseError, SlackApiError)),
        before_sleep=before_sleep_log(test_channel_retry_logger, logging.WARNING)
    )
    def test_channel_connection(team_public_id: str, channel_id: str, db: Session = None) -> Dict[str, Any]:
        """
        Test if the bot can post to a specific channel
        
        Args:
            team_public_id: Public ID of the team
            channel_id: Channel ID to test
            db: Database session
            
        Returns:
            Dict containing success status and any errors
        """
        log = new_logger(f"test_channel_connection_{team_public_id}")
        
        if not db:
            db = next(get_db())
        
        try:
            # Get team data
            team = db.query(Team).filter_by(public_id=team_public_id).first()
            if not team:
                return {
                    "success": False,
                    "error": "Team not found",
                    "message": "The specified team could not be found"
                }
            
            # Get Slack installation from team settings
            if not team.slack_settings or not isinstance(team.slack_settings, dict):
                return {
                    "success": False,
                    "error": "No Slack integration",
                    "message": "This team doesn't have Slack integration set up"
                }
            
            slack_app_data = team.slack_settings.get("slack_app")
            if not slack_app_data or not isinstance(slack_app_data, dict):
                return {
                    "success": False,
                    "error": "No Slack integration",
                    "message": "This team doesn't have Slack integration set up"
                }
            
            bot_token = slack_app_data.get('bot_token')
            if not bot_token:
                return {
                    "success": False,
                    "error": "Invalid Slack integration",
                    "message": "Slack integration is incomplete"
                }
            
            # Generate test message blocks
            blocks = SlackBlocksService.channel_test_message(f"#{channel_id}")
            
            # Post test message to Slack
            client = WebClient(token=bot_token)
            
            response = client.chat_postMessage(
                channel=channel_id,
                blocks=blocks,
                text="Welcomepage channel test"
            )
            
            if response["ok"]:
                log.info(f"Successfully posted test message to channel: {channel_id}")
                return {
                    "success": True,
                    "message": "Channel test successful",
                    "slack_response": {
                        "channel": response["channel"],
                        "timestamp": response["ts"]
                    }
                }
            else:
                log.error(f"Channel test failed: {response}")
                return {
                    "success": False,
                    "error": "Channel test failed",
                    "message": "Failed to post test message to channel"
                }
                
        except SlackApiError as e:
            log.error(f"Slack API error during channel test: {e.response['error']}")
            error_msg = e.response.get('error', 'Unknown Slack error')
            
            if error_msg == 'channel_not_found':
                user_message = "Channel not found. Please check the channel name."
            elif error_msg == 'not_in_channel':
                user_message = "The Welcomepage bot is not in this channel. Please invite the bot first."
            elif error_msg == 'access_denied':
                user_message = "Access denied. The bot may not have permission to post in this channel."
            else:
                user_message = f"Slack error: {error_msg}"
            
            return {
                "success": False,
                "error": "Slack API error",
                "message": user_message,
                "slack_error": error_msg
            }
            
        except (OperationalError, IntegrityError, DataError, DatabaseError, SlackApiError):
            # These exceptions are handled by the @retry decorator - let them bubble up
            raise
        except Exception as e:
            # Only catch non-retryable exceptions here
            log.error(f"Non-retryable error during channel test: {str(e)}")
            return {
                "success": False,
                "error": "Internal error",
                "message": "An unexpected error occurred during channel test"
            }
