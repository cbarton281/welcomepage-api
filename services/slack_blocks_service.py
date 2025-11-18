import os
from typing import Dict, Any, List, Optional
from string import Template
import requests
from utils.logger_factory import new_logger


class SlackBlocksService:
    """Service for generating Slack block kit UI components"""
    
    @staticmethod
    def get_valid_image_url(image_url: Optional[str]) -> str:
        """Validate image URL and return default if invalid"""
        log = new_logger("get_valid_image_url")
        log.info(f"Validating image_url: {image_url}")
        
        # Get webapp URL from environment
        wp_webapp_url = os.getenv('WEBAPP_URL')
        default_url = f"{wp_webapp_url}/default_wave.gif"
        
        if not image_url:
            log.info(f"No image_url provided, using default: {default_url}")
            return default_url
        
        # Check if it's a valid URL format (starts with http:// or https://)
        if not (image_url.startswith('http://') or image_url.startswith('https://')):
            log.warning(f"Invalid URL format: {image_url}, using default")
            return default_url
        
        # For Slack, we trust that Supabase public URLs are accessible
        # Don't do HEAD request validation as it can fail due to CORS/timeout
        # and Slack will handle broken images gracefully
        log.info(f"Using image_url: {image_url}")
        return image_url
    
    @staticmethod
    def user_not_found_blocks(display_name: str) -> List[Dict[str, Any]]:
        """Generate blocks for when a user hasn't created their welcomepage yet"""
        wp_webapp_url = os.getenv('WEBAPP_URL')
        
        text_str = Template(
            "@$user hasn't shared their story yet on Welcomepage. \n\n Ping them and ask them to do it!"
        ).substitute(user=display_name)
        
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": text_str
                },
                "accessory": {
                    "type": "image",
                    "image_url": f"{wp_webapp_url}/placeholder-user.jpg",
                    "alt_text": "profile not found"
                }
            }
        ]
        return blocks
    
    @staticmethod
    def user_found_blocks(user_data: Dict[str, Any], team_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate blocks for when a user has created their welcomepage"""
        wp_webapp_url = os.getenv('WEBAPP_URL')
        
        # Extract user information
        full_name = user_data.get('name', 'Unknown User')
        title = user_data.get('role', 'Team Member')
        location = user_data.get('location', 'Unknown Location')
        public_id = user_data.get('public_id')
        wave_gif_url = user_data.get('wave_gif_url')
        
        # Build summary text
        template_str = Template("*$full_name*\n $title \n $location \n \n _*> *_")
        summary_paragraph = template_str.substitute(
            full_name=full_name, 
            title=title, 
            location=location
        )
        
        # Build button label
        button_label_template = Template("Go to $full_name's Welcomepage")
        button_label = button_label_template.substitute(full_name=full_name)
        
        # Build welcomepage URL
        wp_url = f"{wp_webapp_url}/view/{public_id}"
        
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": summary_paragraph
                }
            }
        ]
        
        # Add wave gif if available
        if wave_gif_url:
            # Validate wave gif URL
            validated_wave_url = SlackBlocksService.get_valid_image_url(wave_gif_url)
            blocks.append({
                "type": "image",
                "title": {
                    "type": "plain_text",
                    "text": f"{full_name}'s Wave",
                    "emoji": True
                },
                "block_id": "wave_gif",
                "image_url": validated_wave_url,
                "alt_text": f"Wave animation from {full_name}"
            })
        else:
            # Use default wave gif if not available
            blocks.append({
                "type": "image",
                "title": {
                    "type": "plain_text",
                    "text": f"{full_name}'s Wave",
                    "emoji": True
                },
                "block_id": "wave_gif",
                "image_url": f"{wp_webapp_url}/default_wave.gif",
                "alt_text": f"Wave animation from {full_name}"
            })
        
        blocks.extend([
            {
                "type": "divider"
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": button_label
                        },
                        "url": wp_url
                    }
                ]
            }
        ])
        return blocks
    
    @staticmethod
    def new_user_blocks(user_name: str, company_name: str, signup_url: str, examples_url: Optional[str] = None) -> List[Dict[str, Any]]:
        """Generate blocks for welcoming a new user"""
        log = new_logger("new_user_blocks")
        log.info(f"Generating new user blocks for {user_name} at {company_name}")
        
        wp_webapp_url = os.getenv('WEBAPP_URL')
        
        # Header text
        header_template = Template("Hi $userName, welcome to $companyName! :wave: :heart:")
        header_str = header_template.substitute(userName=user_name, companyName=company_name)
        
        # Section text
        section_template = Template(
            "At $companyName, we ask every new starter to create a Welcomepage to help introduce yourself to the team."
        )
        section_str = section_template.substitute(companyName=company_name)
        
        wave_image_url = f"{wp_webapp_url}/new-member-wave.png"
        
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": header_str,
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": section_str
                },
                "accessory": {
                    "type": "image",
                    "image_url": wave_image_url,
                    "alt_text": "Illustration of woman waving"
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "url": signup_url,
                        "text": {
                            "type": "plain_text",
                            "text": "Start My Welcomepage",
                            "emoji": True
                        },
                        "value": "start_my_story_click",
                        "action_id": "start_my_story_button",
                        "style": "primary"
                    }
                ]
            }
        ]
        # Optionally append a secondary button to the actions block
        try:
            if examples_url:
                # Add secondary button to the right of the primary button
                actions_block = next((b for b in blocks if b.get("type") == "actions"), None)
                if actions_block and isinstance(actions_block.get("elements"), list):
                    actions_block["elements"].append({
                        "type": "button",
                        "url": examples_url,
                        "text": {
                            "type": "plain_text",
                            "text": "See some examples",
                            "emoji": True
                        },
                        "value": "see_examples_click",
                        "action_id": "see_examples_button"
                    })
        except Exception as e:
            # Do not fail message generation if secondary button can't be added
            log.error(f"Failed to append examples button: {str(e)}")
        return blocks
    
    @staticmethod
    def app_home_page_blocks(
        signup_url: str, 
        has_published_page: bool, 
        is_new_user: bool,
        organization_name: str = "your team"
    ) -> Dict[str, Any]:
        """Generate the main app home page blocks"""
        
        # Determine section text and button text based on user state
        if has_published_page:
            section_text = "Wahoo, you've created your Welcomepage! :clinking_glasses:"
            button_text = "Edit My Welcomepage"
        else:
            section_text = "Connect with your team by creating a Welcomepage."
            button_text = "Start My Welcomepage"
        
        return {
            "type": "home",
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "Hello from Welcomepage! :wave:",
                        "emoji": True
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Create or edit Your Welcomepage*"
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": section_text
                    }
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": button_text,
                                "emoji": True
                            },
                            "value": "sign_up_click",
                            "action_id": "sign_up_button",
                            "url": signup_url
                        }
                    ]
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Learn more about your colleagues*"
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "To find your teammates' Welcomepages, use the slash command `/welcomepage @teammember`, or find the link to their Welcomepage in their Slack sidebar."
                    }
                }
            ]
        }
    
    @staticmethod
    def story_publish_blocks(
        user_data: Dict[str, Any], 
        team_data: Dict[str, Any], 
        custom_msg: str = ""
    ) -> List[Dict[str, Any]]:
        """Generate blocks for when a user publishes their story"""
        log = new_logger("story_publish_blocks")
        log.info(f"user_data: {user_data}")
        log.info(f"team_data: {team_data}")
        log.info(f"custom_msg: {custom_msg}")
        
        wp_webapp_url = os.getenv('WEBAPP_URL')
        
        # Extract user information
        slack_user_id = user_data.get('slack_user_id')
        full_name = user_data.get('name', 'Unknown User')
        nickname = user_data.get('nickname') or full_name.split()[0] if full_name else 'User'
        role = user_data.get('role', 'Team Member')
        location = user_data.get('location', 'Unknown Location')
        public_id = user_data.get('public_id')
        wave_gif_url = user_data.get('wave_gif_url')
        
        # Build welcomepage URL
        wp_url = f"{wp_webapp_url}/view/{public_id}"
        
        # Build main message
        template_str = Template("*Location:* $location \n*Role:* $role \n*$nickname's Welcomepage*: $wp_url")
        msg_markdown = template_str.substitute(
            location=location, 
            role=role, 
            nickname=nickname, 
            wp_url=wp_url
        )
        
        welcome_str = f"Welcome <@{slack_user_id}>!" if slack_user_id else f"Welcome {full_name}!"
        
        # Handle wave gif URL
        if not wave_gif_url:
            wave_gif_url = f"{wp_webapp_url}/default_wave.gif"
            log.warning(f"Wave URL not specified using default")
        
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": welcome_str
                }
            },
            {
                "type": "image",
                "title": {
                    "type": "plain_text",
                    "text": f"{nickname}'s Wave",
                    "emoji": True
                },
                "block_id": "wave_gif",
                "image_url": wave_gif_url,
                "alt_text": f"Wave animation from {full_name}"
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": msg_markdown
                }
            }
        ]
        
        # Add custom message if provided
        if custom_msg and custom_msg.strip():
            custom_msg_markdown = f"*Message from* <@{slack_user_id}>: {custom_msg}" if slack_user_id else f"*Message from {full_name}*: {custom_msg}"
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": custom_msg_markdown
                }
            })
        
        log.info(f"Generated publish blocks for user {full_name}")
        return blocks
    
    @staticmethod
    def channel_test_message(channel_name: str) -> List[Dict[str, Any]]:
        """Generate test message for channel integration"""
        log = new_logger("channel_test_message")
        log.info(f"Generating test message for channel: {channel_name}")
        
        markdown = f"It works! :white_check_mark:  *{channel_name}* is now ready to receive Welcomepage messages."
        
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": markdown
                }
            }
        ]
        return blocks
