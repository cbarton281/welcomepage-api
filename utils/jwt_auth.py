from fastapi import Depends, HTTPException, status
from fastapi.security.api_key import APIKeyHeader
from jose import JWTError, jwt
import os
from utils.logger_factory import new_logger

SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("JWT_SECRET_KEY environment variable must be set for JWT authentication.")
    
ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")

api_key_header = APIKeyHeader(name="Authorization")

def get_current_user(api_key: str = Depends(api_key_header)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    log = new_logger("get_current_user")
    if not api_key.startswith("Bearer "):
        raise credentials_exception
    token = api_key[len("Bearer "):]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        role = payload.get("role")
        log.info(f"User ID: {user_id}, Role: {role}")
        if user_id is None or role is None:
            log.exception("Invalid JWT: missing user ID or role.")
            raise credentials_exception
        return {"user_id": user_id, "role": role}
    except JWTError:
        log.exception("JWT decoding failed.")
        raise credentials_exception

def require_roles(*roles):
    def role_checker(user=Depends(get_current_user)):
        if user["role"] not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return user
    return role_checker
