import secrets
import string
import random

def generate_short_id(length: int = 10) -> str:
    """
    Generate a cryptographically secure short alphanumeric ID using lowercase letters and digits.
    
    Args:
        length: Length of the ID to generate (default: 10)
        
    Returns:
        String containing random a-z0-9 characters
        
    Example:
        generate_short_id() -> "k3m9x7q2w5"
        generate_short_id(8) -> "a4b7c9d2"
    """
    # Use lowercase letters and digits (36 possible characters)
    characters = string.ascii_lowercase + string.digits  # a-z0-9
    
    # Generate cryptographically secure random ID
    return ''.join(secrets.choice(characters) for _ in range(length))


def generate_short_id_with_collision_check(db, table_class, id_type: str, max_attempts: int = 5) -> str:
    """
    Generate a short ID with collision detection.
    
    Args:
        db: Database session
        table_class: SQLAlchemy model class (Team or WelcomepageUser)
        id_type: Type of ID being generated ("user" or "team") for logging
        max_attempts: Maximum number of generation attempts
        
    Returns:
        Unique short ID
        
    Raises:
        Exception: If unable to generate unique ID after max_attempts
    """
    import logging
    logger = logging.getLogger(__name__)
    
    for attempt in range(max_attempts):
        short_id = generate_short_id()
        
        # Check if ID already exists
        existing = db.query(table_class).filter_by(public_id=short_id).first()
        if not existing:
            logger.info(f"Generated unique {id_type} ID: {short_id}")
            return short_id
            
        logger.warning(f"ID collision detected for {id_type}: {short_id} (attempt {attempt + 1}/{max_attempts})")
    
    raise Exception(f"Failed to generate unique {id_type} ID after {max_attempts} attempts")


def generate_file_id(public_id: str = None) -> str:
    """
    Generate an ID for file naming purposes.
    Uses the provided public_id if available, otherwise generates a new short ID.
    
    WARNING: If public_id is None, this indicates a potential bug in the authentication/ID flow.
    Files created without a proper public_id may become orphaned and difficult to recover.
    
    Args:
        public_id: Optional public ID to use (from user/team)
        
    Returns:
        String to use for file naming
        
    Example:
        generate_file_id("abc123def0") -> "abc123def0"
        generate_file_id(None) -> "k3m9x7q2w5" (with error logged)
    """
    if public_id:
        return public_id
    
    # This should NOT happen in normal operation - log the error
    import logging
    import traceback
    from datetime import datetime
    
    logger = logging.getLogger(__name__)
    fallback_id = generate_short_id()
    
    # Log detailed error information for debugging
    logger.error(
        f"CRITICAL: File ID generated without public_id! "
        f"Using fallback ID: {fallback_id}. "
        f"This indicates a bug in the authentication/ID flow. "
        f"File may become orphaned. "
        f"Timestamp: {datetime.now().isoformat()}"
    )
    
    # Also log the stack trace to help identify where this is being called from
    logger.error(f"Stack trace for missing public_id: {traceback.format_stack()}")
    
    return fallback_id
