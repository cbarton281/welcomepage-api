import os
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from database import Base, get_db, SessionLocal
from models.welcomepage_user import WelcomepageUser
from schemas.welcomepage_user import WelcomepageUserDTO
from utils.logger_factory import new_logger


app = FastAPI()

from fastapi import Request

@app.middleware("http")
async def log_request_body(request: Request, call_next):
    log = new_logger("log_request_body")
    log.info(f"INCOMING REQUEST: {request.method} {request.url}")
    if request.method != "OPTIONS":  # Skip CORS preflight
        body = await request.body()
        
        # Check content type to avoid logging binary data
        content_type = request.headers.get("content-type", "")
        if "multipart/form-data" in content_type:
            # For multipart data, only log that it contains form data, not the binary content
            log.info(f"Request body ({request.method} {request.url.path}): multipart/form-data (binary content excluded from logs)")
        elif len(body) > 0:
            # For other content types, log first 1000 chars (reduced from 3000)
            log.info(f"Request body ({request.method} {request.url.path}): {body[:1000]!r}")
        
        # Recreate request with the consumed body
        request = Request(request.scope, receive=lambda: {"type": "http.request", "body": body})
    response = await call_next(request)
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()



@app.get("/")
def root():
    return {"message": "Welcomepage API deployed.  Note: the DB connection has not been verified yet."}

from api.user import router as users_router
from api.team import router as team_router
from api.verification_code import router as verification_code_router
from api.reactions import router as reactions_router
from api.page_comments import router as comments_router
from api.id_check import router as id_check_router
from api.visits import router as visits_router
from api.healthcheck import router as health_router
from api.slack import router as slack_router
from api.slack_publish import router as slack_publish_router
from api.deployment import router as deployment_router
from api.public_join import router as public_join_router
from api.slack_redirect import router as slack_redirect_router
from api.spotify import router as spotify_router
from api.google import router as google_router

app.include_router(users_router, prefix="/api")
app.include_router(team_router, prefix="/api")
app.include_router(verification_code_router, prefix="/api")
app.include_router(reactions_router, prefix="/api/reactions")
app.include_router(comments_router, prefix="/api/comments")
app.include_router(id_check_router, prefix="/api")
app.include_router(visits_router, prefix="/api")
app.include_router(health_router, prefix="/api")
app.include_router(slack_router, prefix="/api/slack")
app.include_router(slack_publish_router, prefix="/api/slack")
app.include_router(deployment_router, prefix="/api")
app.include_router(public_join_router, prefix="/api")
app.include_router(slack_redirect_router, prefix="/api")
app.include_router(spotify_router, prefix="/api")
app.include_router(google_router, prefix="/api")
