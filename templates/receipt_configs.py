"""
Receipt Template Configurations
Store different template configurations for different use cases
"""

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, letter

# Default template configuration
DEFAULT_RECEIPT_CONFIG = {
    'company_name': 'Welcomepage',
    'company_tagline': '',  # Removed default tagline
    'primary_color': colors.darkblue,
    'secondary_color': colors.grey,
    'contact_email': 'support@welcomepage.com',
    'page_size': A4
    # Logo is now fetched dynamically from WEBAPP_URL/welcomepage_logo.png
}

# Enterprise template configuration
ENTERPRISE_RECEIPT_CONFIG = {
    'company_name': 'Welcomepage Enterprise',
    'company_tagline': 'Enterprise Welcome Page Solutions',
    'primary_color': colors.darkgreen,
    'secondary_color': colors.darkgrey,
    'contact_email': 'enterprise@welcomepage.com',
    'page_size': A4
    # Logo is now fetched dynamically from WEBAPP_URL/welcomepage_logo.png
}

# Minimal template configuration
MINIMAL_RECEIPT_CONFIG = {
    'company_name': 'Welcomepage',
    'company_tagline': '',
    'primary_color': colors.black,
    'secondary_color': colors.grey,
    'contact_email': 'support@welcomepage.com',
    'page_size': A4
    # Logo is now fetched dynamically from WEBAPP_URL/welcomepage_logo.png
}

# Custom template configuration (can be loaded from database or config file)
CUSTOM_RECEIPT_CONFIG = {
    'company_name': 'Your Company Name',
    'company_tagline': 'Your Company Tagline',
    'primary_color': colors.purple,
    'secondary_color': colors.lightgrey,
    'contact_email': 'billing@yourcompany.com',
    'page_size': letter
    # Logo is now fetched dynamically from WEBAPP_URL/welcomepage_logo.png
}

# Template registry - maps template names to configurations
TEMPLATE_REGISTRY = {
    'default': DEFAULT_RECEIPT_CONFIG,
    'enterprise': ENTERPRISE_RECEIPT_CONFIG,
    'minimal': MINIMAL_RECEIPT_CONFIG,
    'custom': CUSTOM_RECEIPT_CONFIG
}

def get_template_config(template_name: str = 'default'):
    """
    Get template configuration by name
    
    Args:
        template_name: Name of the template ('default', 'enterprise', 'minimal', 'custom')
        
    Returns:
        Template configuration dictionary
    """
    return TEMPLATE_REGISTRY.get(template_name, DEFAULT_RECEIPT_CONFIG)

def get_team_template_config(team_id: str):
    """
    Get template configuration for a specific team
    This could be extended to load from database or team settings
    
    Args:
        team_id: Team identifier
        
    Returns:
        Template configuration dictionary
    """
    # For now, return default config
    # In the future, this could load team-specific branding from database
    return DEFAULT_RECEIPT_CONFIG
