# Coding Standards for welcomepage-api

This document establishes comprehensive coding standards for the welcomepage-api FastAPI project to ensure consistency, reliability, and maintainability.

## 1. Database Access with Tenacity Retries

### Mandatory Tenacity Usage
**ALL database operations MUST use tenacity retries.** This includes:
- Database read operations (SELECT, queries)
- Database write operations (INSERT, UPDATE, DELETE)
- External API calls (Slack, email services, etc.)
- Any operation that could encounter transient failures

### Required Pattern
```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log
from sqlalchemy.exc import OperationalError, IntegrityError, DataError, DatabaseError
from slack_sdk.errors import SlackApiError
import logging

# Create a retry logger for each method
method_retry_logger = new_logger("method_name_retry")

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((OperationalError, IntegrityError, DataError, DatabaseError, SlackApiError)),
    before_sleep=before_sleep_log(method_retry_logger, logging.WARNING)
)
def your_database_method(db: Session = Depends(get_db)):
    # Database operations here
    pass
```

### Exception Types to Retry
**CRITICAL:** Only retry specific transient exceptions. NEVER use broad exception types:

**✅ SAFE TO RETRY:**
- `OperationalError`: Database connection issues
- `IntegrityError`: Constraint violations that may be transient
- `DataError`: Data type conversion issues
- `DatabaseError`: General database errors
- `SlackApiError`: Slack API rate limits and transient errors
- `requests.exceptions.RequestException`: HTTP request failures
- `ConnectionError`: Network connectivity issues

**❌ NEVER RETRY:**
- `Exception`: Base class - will retry ALL exceptions including programming errors
- `ValueError`: Programming/validation errors
- `AttributeError`: Programming errors
- `KeyError`: Programming errors
- `HTTPException`: Business logic errors (404, 403, etc.)

**IMPORTANT:** The `@retry` decorator MUST catch all exceptions that could be transient. If you use a broad `except Exception as e:` block, those exceptions will NOT be retried and the method will exit immediately.

### Exception Handling with Retries
When using `@retry` decorators, exception handling MUST follow this pattern to avoid bypassing retries:

```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((OperationalError, IntegrityError, DataError, DatabaseError, SlackApiError)),
    before_sleep=before_sleep_log(method_retry_logger, logging.WARNING)
)
def your_method():
    log = new_logger("your_method")
    
    try:
        # Method implementation
        pass
    except SlackApiError as e:
        # Handle specific exceptions with user-friendly messages
        log.error(f"Slack API error: {e.response['error']}")
        return {"success": False, "error": "Slack API error"}
    except (OperationalError, IntegrityError, DataError, DatabaseError, SlackApiError):
        # CRITICAL: Re-raise retryable exceptions so @retry decorator can handle them
        raise
    except Exception as e:
        # Only catch truly non-retryable exceptions (programming errors, etc.)
        log.error(f"Non-retryable error: {str(e)}")
        return {"success": False, "error": "Internal error"}
```

**CRITICAL RULE:** Any exception listed in `retry_if_exception_type()` MUST be re-raised in the exception handler, otherwise retries will be bypassed.

### When NOT to Use Retries
- Operations inside database transactions (to avoid holding locks)
- Business logic validation (404, 403 errors should fail immediately)
- User input validation errors

## 2. Logging Standards

### Logger Creation
ALWAYS use `new_logger()` to get a logger instance for each method:

```python
from utils.logger_factory import new_logger

def your_method():
    log = new_logger("your_method_name")
    # Method implementation
```

### First Operation Logging
ALWAYS log an info message as the FIRST operation in every API route with parameters:

```python
@router.post("/your-endpoint")
def your_endpoint(param1: str, param2: int, db: Session = Depends(get_db)):
    log = new_logger("your_endpoint")
    log.info(f"Starting your_endpoint with param1={param1}, param2={param2}")
    
    # Rest of implementation
```

### Separate Logger Per Method
Each method MUST have its own logger instance:

```python
# ✅ CORRECT - Each method gets its own logger
def method_one():
    log = new_logger("method_one")
    log.info("Method one started")

def method_two():
    log = new_logger("method_two")
    log.info("Method two started")

# ❌ INCORRECT - Sharing loggers between methods
log = new_logger("shared_logger")  # Don't do this
```

### Retry Logger Pattern
For methods using tenacity retries, create a separate retry logger:

```python
# At module level
method_retry_logger = new_logger("method_name_retry")

@retry(before_sleep=before_sleep_log(method_retry_logger, logging.WARNING))
def your_method():
    log = new_logger("method_name")  # Separate logger for method logic
    # Implementation
```

## 3. Pydantic Schema Standards

### Schema Updates
Pydantic schemas MUST always be updated when:
- Adding new fields to database models
- Modifying existing field types
- Adding new API endpoints
- Changing response structures

### Schema Organization
```python
# Request schemas
class CreateItemRequest(BaseModel):
    name: str
    description: Optional[str] = None

# Response schemas  
class ItemResponse(BaseModel):
    id: int
    public_id: str
    name: str
    created_at: datetime

# List response schemas
class ItemListResponse(BaseModel):
    items: List[ItemResponse]
    total_count: int
    page: int
    page_size: int
```

### Required Schema Fields
All response schemas MUST include:
- `public_id` for external references
- Timestamp fields (`created_at`, `updated_at`)
- Proper Optional typing for nullable fields

## 4. API Route Standards

### Route Structure
```python
@router.post("/endpoint", response_model=ResponseSchema)
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(OperationalError),
    before_sleep=before_sleep_log(retry_logger, logging.WARNING)
)
def endpoint_handler(
    request: RequestSchema,
    current_user: dict = Depends(require_roles(["USER", "ADMIN"])),
    db: Session = Depends(get_db)
):
    log = new_logger("endpoint_handler")
    log.info(f"Starting endpoint_handler with request={request.dict()}")
    
    try:
        # Implementation
        log.info("Successfully completed endpoint_handler")
        return result
    except Exception as e:
        log.error(f"Error in endpoint_handler: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")
```

### Authentication Pattern
Use consistent authentication patterns:
```python
# For admin-only endpoints
current_user: dict = Depends(require_roles(["ADMIN"]))

# For user and admin endpoints
current_user: dict = Depends(require_roles(["USER", "ADMIN"]))

# Always log the user context
log.info(f"User {current_user.get('public_id')} accessing endpoint")
```

## 5. Error Handling Standards

### Exception Handling
```python
try:
    # Database operations
    result = db.query(Model).filter(...).first()
    if not result:
        log.warning(f"Resource not found with id={resource_id}")
        raise HTTPException(status_code=404, detail="Resource not found")
        
except OperationalError as e:
    log.error(f"Database error: {str(e)}")
    raise HTTPException(status_code=500, detail="Database error")
except Exception as e:
    log.error(f"Unexpected error: {str(e)}")
    raise HTTPException(status_code=500, detail="Internal server error")
```

### HTTP Status Codes
- `200`: Success
- `201`: Created
- `400`: Bad Request (validation errors)
- `401`: Unauthorized (authentication required)
- `403`: Forbidden (insufficient permissions)
- `404`: Not Found
- `409`: Conflict (duplicate resources)
- `500`: Internal Server Error

## 6. Database Model Standards

### Model Structure
```python
from sqlalchemy import Column, Integer, String, DateTime, JSON, Boolean
from sqlalchemy.sql import func
from database import Base

class YourModel(Base):
    __tablename__ = "your_table"
    
    id = Column(Integer, primary_key=True, index=True)
    public_id = Column(String(10), unique=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    def to_dict(self):
        return {
            "id": self.id,
            "public_id": self.public_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
```

### Required Model Fields
All models MUST include:
- `id`: Primary key
- `public_id`: External reference (10-character string)
- `created_at`: Timestamp with timezone
- `updated_at`: Auto-updating timestamp
- `to_dict()`: Method for serialization

## 7. Import Standards

### Required Imports Order
```python
# Standard library imports
import json
import logging
from datetime import datetime
from typing import Optional, List

# Third-party imports
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError
from tenacity import retry, stop_after_attempt, wait_exponential

# Local imports
from database import get_db
from models.your_model import YourModel
from schemas.your_schema import YourSchema
from utils.logger_factory import new_logger
from utils.jwt_auth import require_roles
```

## 8. Environment Variables

### Required Environment Variables
All environment variables MUST be documented and explicitly required:

```python
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is required")
```

## 9. Testing Standards

### Test Structure
```python
import pytest
from fastapi.testclient import TestClient
from utils.logger_factory import new_logger

def test_endpoint():
    log = new_logger("test_endpoint")
    log.info("Starting test_endpoint")
    
    # Test implementation
    assert response.status_code == 200
    log.info("test_endpoint completed successfully")
```

## 10. Documentation Standards

### Docstring Requirements
All functions MUST have docstrings:

```python
def your_function(param1: str, param2: int) -> dict:
    """
    Brief description of what the function does.
    
    Args:
        param1: Description of param1
        param2: Description of param2
        
    Returns:
        Description of return value
        
    Raises:
        HTTPException: When validation fails
    """
    log = new_logger("your_function")
    log.info(f"Starting your_function with param1={param1}, param2={param2}")
```

## 11. Security Standards

### JWT Authentication
```python
from utils.jwt_auth import require_roles

# Always validate user permissions
current_user: dict = Depends(require_roles(["ADMIN"]))

# Always log security-relevant operations
log.info(f"Admin user {current_user.get('public_id')} performing sensitive operation")
```

### Input Validation
```python
from pydantic import BaseModel, validator

class RequestSchema(BaseModel):
    email: str
    
    @validator('email')
    def validate_email(cls, v):
        if '@' not in v:
            raise ValueError('Invalid email format')
        return v.lower()
```

## 12. Performance Standards

### Database Queries
- Always use proper indexing
- Implement pagination for list endpoints
- Use `select_related` for foreign key relationships
- Limit query results with reasonable defaults

### Connection Pooling
```python
# In database.py
engine = create_engine(
    DATABASE_URL,
    pool_size=2,        # Small pool size for serverless
    max_overflow=0      # No extra connections
)
```

## Enforcement

These rules are automatically enforced by Cascade AI assistant. All code changes must follow these patterns. Violations will be flagged and must be corrected before code review approval.

## Examples

See existing files for reference implementations:
- `/api/user.py` - Complete API route example
- `/api/team.py` - Team management patterns
- `/utils/logger_factory.py` - Logging implementation
- `/models/welcomepage_user.py` - Model structure example
