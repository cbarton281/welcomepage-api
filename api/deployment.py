import os
import subprocess
from fastapi import APIRouter, Depends
from utils.jwt_auth import require_roles
from utils.logger_factory import new_logger

router = APIRouter()
log = new_logger("deployment_api")

def deployment_meta():
    """Get deployment metadata from environment variables (Vercel or local dev)"""
    # Check if we're running on Vercel
    is_vercel = bool(os.getenv("VERCEL"))
    log.info(f"is_vercel: {is_vercel}")
    
    if is_vercel:
        # Vercel deployment
        env = os.getenv("VERCEL_ENV", "unknown")
        deployment_id = os.getenv("VERCEL_DEPLOYMENT_ID")
        url = os.getenv("VERCEL_URL")
        region = os.getenv("VERCEL_REGION")
        git_sha = os.getenv("VERCEL_GIT_COMMIT_SHA")
        branch = os.getenv("VERCEL_GIT_COMMIT_REF")
        
        display = f"{env}:{git_sha[:7] if git_sha else 'unknown'}@{deployment_id[:8] if deployment_id else 'unknown'}"
    else:
        # Local development
        env = "local"
        deployment_id = None
        url = "localhost"
        region = "local"
        git_sha = None
        branch = None
        
        # Try to get git info for local development
        try:
            # Get current git branch
            branch_result = subprocess.run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], 
                                         capture_output=True, text=True, timeout=5)
            if branch_result.returncode == 0:
                branch = branch_result.stdout.strip()
            
            # Get current git commit SHA
            sha_result = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], 
                                      capture_output=True, text=True, timeout=5)
            if sha_result.returncode == 0:
                git_sha = sha_result.stdout.strip()
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
            # Git not available or not in a git repo
            pass
        
        display = f"local:{git_sha or 'dev'}@dev"
    
    return {
        "env": env,
        "deployment_id": deployment_id,
        "url": url,
        "region": region,
        "git_sha": git_sha[:7] if git_sha and len(git_sha) > 7 else git_sha,
        "branch": branch,
        "display": display,
        "is_vercel": is_vercel,
    }

@router.get("/_meta")
def meta(current_user=Depends(require_roles("ADMIN"))):
    """Protected endpoint to get deployment metadata - requires ADMIN role"""
    log.info(f"Deployment metadata requested by user: {current_user.get('user_id')}")
    return deployment_meta()
