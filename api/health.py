from fastapi import FastAPI, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db
from utils.logger_factory import new_logger

app = FastAPI()

@app.get("/api/health")
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
            
    except Exception as e:
        log.error(f"Health check failed with exception: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "status": "unhealthy", 
                "message": "Database connection failed",
                "database": "disconnected",
                "error": str(e)
            }
        )
