"""
Utility functions for checking team limits and subscription status.
"""
from sqlalchemy.orm import Session
from models.team import Team
from models.welcomepage_user import WelcomepageUser
from utils.logger_factory import new_logger

def check_team_signup_allowed(db: Session, team_id: int) -> tuple[bool, str]:
    """
    Check if a team can accept new user signups based on free page limits and payment status.
    
    Args:
        db: Database session
        team_id: Internal team ID
        
    Returns:
        tuple: (is_allowed, reason_message)
    """
    log = new_logger("check_team_signup_allowed")
    
    try:
        # Get team information
        team = db.query(Team).filter(Team.id == team_id).first()
        if not team:
            log.warning(f"Team not found for team_id: {team_id}")
            return False, "Team not found"
        
        # UNLIMITED subscription (staff only, set via SQL) bypasses all limits
        if team.subscription_status == 'unlimited':
            log.info(f"Team {team.public_id} has unlimited subscription, bypassing all checks")
            return True, "Signup allowed (unlimited subscription)"
        
        # Count published pages (non-draft users with auth_email)
        published_count = db.query(WelcomepageUser).filter(
            WelcomepageUser.team_id == team_id,
            WelcomepageUser.is_draft == False,
            WelcomepageUser.auth_email.isnot(None),
            WelcomepageUser.auth_email != ''
        ).count()
        
        log.info(f"Team {team.public_id} has {published_count} published pages, stripe_customer_id: {team.stripe_customer_id}, subscription_status: {team.subscription_status}")
        
        # Check subscription status to determine limits
        subscription_status = team.subscription_status or 'free'
        
        # PRO subscription bypasses page count limits
        if subscription_status == 'pro':
            log.info(f"Team {team.public_id} has pro subscription, bypassing page limits")
            return True, "Signup allowed (pro subscription)"
        
        # For FREE subscription, check page limits
        # Free limit is 3 pages
        FREE_LIMIT = 3
        
        # If team has exceeded free limit, block signups
        if published_count >= FREE_LIMIT:
            log.warning(f"Team {team.public_id} has exceeded free limit ({published_count}/{FREE_LIMIT})")
            return False, f"Team has reached the free limit of {FREE_LIMIT} pages. Please upgrade to add more team members."
        
        # Allow signup if under limit
        log.info(f"Team {team.public_id} signup allowed: {published_count}/{FREE_LIMIT} pages")
        return True, "Signup allowed"
        
    except Exception as e:
        log.error(f"Error checking team signup limits for team_id {team_id}: {str(e)}")
        return False, "Error checking team limits"

def check_team_signup_allowed_by_public_id(db: Session, team_public_id: str) -> tuple[bool, str]:
    """
    Check if a team can accept new user signups based on free page limits and payment status.
    
    Args:
        db: Database session
        team_public_id: Team public ID
        
    Returns:
        tuple: (is_allowed, reason_message)
    """
    log = new_logger("check_team_signup_allowed_by_public_id")
    
    try:
        # Get team by public_id
        team = db.query(Team).filter(Team.public_id == team_public_id).first()
        if not team:
            log.warning(f"Team not found for public_id: {team_public_id}")
            return False, "Team not found"
        
        return check_team_signup_allowed(db, team.id)
        
    except Exception as e:
        log.error(f"Error checking team signup limits for team_public_id {team_public_id}: {str(e)}")
        return False, "Error checking team limits"
