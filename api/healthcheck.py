from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log
import logging
from database import get_db
from utils.logger_factory import new_logger

# Create retry logger
health_retry_logger = new_logger("health_check_retry")

router = APIRouter()

@router.get("/health")
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(OperationalError),
    before_sleep=before_sleep_log(health_retry_logger, logging.WARNING)
)
def health_check(db: Session = Depends(get_db)):
    """
    Health check endpoint that performs a benign database operation
    to keep Vercel serverless and Supabase warm while monitoring API status.
    
    Returns:
        200: Service is healthy and database is accessible
        500: Service is unhealthy or database is unreachable
    """
    log = new_logger("health_check")
    
    try:
        # Perform a simple, benign database query
        result = db.execute(text("SELECT 1 as health_check"))
        row = result.fetchone()
        
        if row and row[0] == 1:
            log.info("Health check passed - database is accessible")
            return {
                "status": "healthy",
                "message": "API and database are operational",
                "database": "connected"
            }
        else:
            log.error("Health check failed - unexpected database response")
            raise HTTPException(
                status_code=500, 
                detail={
                    "status": "unhealthy",
                    "message": "Database query returned unexpected result",
                    "database": "error"
                }
            )
            
    except OperationalError:
        # These exceptions are handled by the @retry decorator - let them bubble up
        raise
    except Exception as e:
        # Only catch non-retryable exceptions here
        log.error(f"Health check failed with non-retryable exception: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "status": "unhealthy",
                "message": "Database connection failed",
                "database": "disconnected",
                "error": str(e)
            }
        )
