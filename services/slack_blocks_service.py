import os
from typing import Dict, Any, List, Optional
from string import Template
import requests
from utils.logger_factory import new_logger


class SlackBlocksService:
    """Service for generating Slack block kit UI components"""
    
    @staticmethod
    def get_valid_image_url(image_url: str) -> str:
        """Validate image URL and return default if invalid"""
        log = new_logger("get_valid_image_url")
        log.info(f"Validating image_url: {image_url}")
        
        # Get webapp URL from environment
        wp_webapp_url = os.getenv('WEBAPP_URL')
        default_url = f"{wp_webapp_url}/default_profile.png"
        
        if not image_url:
            return default_url
            
        try:
            resp = requests.head(image_url, timeout=2)
            log.info(f"Image validation - status: {resp.status_code}, content-type: {resp.headers.get('Content-Type', '')}")
            
            if resp.status_code == 200 and resp.headers.get('Content-Type', '').startswith('image/'):
                return image_url
        except Exception as e:
            log.info(f"Exception validating image_url {image_url}: {str(e)}")
            
        return default_url
    
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
                    "image_url": f"{wp_webapp_url}/default_profile.png",
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
        profile_photo_url = user_data.get('profile_photo_url')
        
        # Build summary text
        template_str = Template("*$full_name*\n $title \n $location \n \n _*> *_")
        summary_paragraph = template_str.substitute(
            full_name=full_name, 
            title=title, 
            location=location
        )
        
        # Build button label
        button_label_template = Template("Go to $full_name's Story")
        button_label = button_label_template.substitute(full_name=full_name)
        
        # Build image URL and validate it
        image_url = SlackBlocksService.get_valid_image_url(profile_photo_url)
        image_alt_text = f"{full_name} profile"
        
        # Build welcomepage URL
        wp_url = f"{wp_webapp_url}/view/{public_id}"
        
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": summary_paragraph
                },
                "accessory": {
                    "type": "image",
                    "image_url": image_url,
                    "alt_text": image_alt_text
                }
            },
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
                        "url": wp_url,
                        "action_id": "actionId-0"
                    }
                ]
            }
        ]
        return blocks
    
    @staticmethod
    def new_user_blocks(user_name: str, company_name: str, signup_url: str) -> List[Dict[str, Any]]:
        """Generate blocks for welcoming a new user"""
        log = new_logger("new_user_blocks")
        log.info(f"Generating new user blocks for {user_name} at {company_name}")
        
        wp_webapp_url = os.getenv('WEBAPP_URL')
        
        # Header text
        header_template = Template("Hi $userName, welcome to $companyName! :wave: :heart:")
        header_str = header_template.substitute(userName=user_name, companyName=company_name)
        
        # Section text
        section_template = Template(
            "At $companyName, *we ask every new starter to create a Welcomepage*, "
            "which is like a short blog post to tell us a little bit about yourself."
        )
        section_str = section_template.substitute(companyName=company_name)
        
        wave_image_url = f"{wp_webapp_url}/services/new-member-wave.png"
        
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
        
        # Validate wave gif URL
        if wave_gif_url:
            wave_gif_url = SlackBlocksService.get_valid_image_url(wave_gif_url)
        else:
            wave_gif_url = f"{wp_webapp_url}/default_wave.gif"
        
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
                "image_url": wave_gif_url,
                "alt_text": f"Welcomepage photo for {full_name}"
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
