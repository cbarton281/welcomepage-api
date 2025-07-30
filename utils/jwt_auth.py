from fastapi import Depends, HTTPException, status
from fastapi.security.api_key import APIKeyHeader
from jose import JWTError, jwt
import os
from utils.logger_factory import new_logger

SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("JWT_SECRET_KEY environment variable must be set for JWT authentication.")
    
ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")

api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

def get_current_user(api_key: str = Depends(api_key_header)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    log = new_logger("get_current_user")
    log.info(f"get_current_user called. Received api_key: {api_key}")
    
    if not api_key:
        log.error("Authorization header missing.")
        raise credentials_exception
    if not api_key.startswith("Bearer "):
        log.error(f"Authorization header malformed or missing 'Bearer ': got '{api_key}'")
        raise credentials_exception
    token = api_key[len("Bearer "):]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        role = payload.get("role")
        team_id = payload.get("team_id")
        log.info(f"User ID: {user_id}, Role: {role}, Team ID: {team_id}")
        if user_id is None or role is None:
            log.error(f"Invalid JWT: missing user ID or role. Payload: {payload}")
            raise credentials_exception
        return {"user_id": user_id, "role": role, "team_id": team_id}
    except JWTError as e:
        log.error(f"JWT decoding failed: {str(e)}. Token: {token}")
        raise credentials_exception

def require_roles(*roles):
    """
    Dependency for FastAPI endpoints to require one or more roles.
    Usage: @router.post(..., dependencies=[Depends(require_roles('ADMIN', 'USER', 'PRE_SIGNUP'))])
    """
    def role_checker(user=Depends(get_current_user)):
        log = new_logger("require_roles")
        if user["role"] not in roles:
            log.warning(
                f"Authorization failed: user_id={user.get('user_id')}, role={user.get('role')}, required_roles={roles}"
            )
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        log.info(f"Authorization successful: user_id={user.get('user_id')}, role={user.get('role')}")
        return user
    return role_checker
