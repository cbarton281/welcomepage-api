"""
Utility functions for validating welcomepage completeness before publishing.
"""
import json
from typing import List, Tuple
from models.welcomepage_user import WelcomepageUser
from utils.logger_factory import new_logger


def validate_page_completeness(user: WelcomepageUser, context: str = "publish") -> Tuple[bool, List[str]]:
    """
    Validate that a welcomepage has all required fields before publishing.
    
    Matches frontend validation requirements:
    - Name: not empty and not "Your Name"
    - Role: not empty and not "Role"
    - Bento widgets: at least 1
    - Prompts: at least 3 selected prompts
    - Wave: must have wave_gif_url
    
    Args:
        user: WelcomepageUser instance to validate
        context: Context for error messages ("publish" or "slack")
        
    Returns:
        tuple: (is_valid, list_of_validation_errors)
        - is_valid: True if page is complete, False otherwise
        - list_of_validation_errors: List of missing field descriptions
    """
    validation_errors = []
    
    # Check name: must not be empty and not placeholder
    has_valid_name = user.name and user.name.strip() and user.name.strip() != "Your Name"
    if not has_valid_name:
        validation_errors.append("name")
    
    # Check role: must not be empty and not placeholder
    has_valid_role = user.role and user.role.strip() and user.role.strip() != "Role"
    if not has_valid_role:
        validation_errors.append("role")
    
    # Check bento widgets: must have at least 1
    bento_widgets = user.bento_widgets if isinstance(user.bento_widgets, list) else (json.loads(user.bento_widgets) if isinstance(user.bento_widgets, str) else [])
    has_bento_tile = len(bento_widgets) > 0
    if not has_bento_tile:
        validation_errors.append("at least 1 bento tile")
    
    # Check prompts: must have at least 3 selected prompts (matches frontend: selectedPrompts.length >= 3)
    selected_prompts = user.selected_prompts if isinstance(user.selected_prompts, list) else (json.loads(user.selected_prompts) if isinstance(user.selected_prompts, str) else [])
    has_min_prompts = len(selected_prompts) >= 3
    if not has_min_prompts:
        needed = 3 - len(selected_prompts)
        validation_errors.append(f"at least {needed} more prompt{'s' if needed > 1 else ''}")
    
    # Check wave: must have wave_gif_url (matches frontend: waveGifUrl || waveVideoUrl)
    # Note: waveVideoUrl is temporary frontend state before upload; database only stores wave_gif_url
    has_wave = bool(user.wave_gif_url)
    if not has_wave:
        validation_errors.append("a wave")
    
    is_valid = len(validation_errors) == 0
    return is_valid, validation_errors

