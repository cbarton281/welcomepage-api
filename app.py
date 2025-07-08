import os
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from database import Base, get_db, SessionLocal
from models.welcomepage_user import WelcomepageUser
from schemas.welcomepage_user import WelcomepageUserDTO


app = FastAPI()

import logging
from fastapi import Request

@app.middleware("http")
async def log_request_body(request: Request, call_next):
    if request.method != "OPTIONS":  # Skip CORS preflight
        body = await request.body()
        logging.info(f"Request body ({request.method} {request.url.path}): {body[:3000]!r}")
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
    return {"message": "Welcome to the WelcomePage API!"}

@app.get("/api/hello")
def hello():
    return {"message": "Hello from FastAPI!"}

from api.users import router as users_router
from api.team import router as team_router

app.include_router(users_router, prefix="/api")
app.include_router(team_router, prefix="/api")

