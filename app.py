import os
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from database import Base, get_db, SessionLocal
from models.welcomepage_user import WelcomepageUser
from schemas.welcomepage_user import WelcomepageUserDTO

# Ensure tables are created
Base.metadata.create_all(bind=SessionLocal.kw['bind'])

app = FastAPI()

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

@app.get("/api/hello")
def hello():
    return {"message": "Hello from FastAPI!"}

from api.users import router as users_router
from api.team import router as team_router

app.include_router(users_router)
app.include_router(team_router, prefix="/api")

