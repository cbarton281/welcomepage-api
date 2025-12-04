from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Fetch DATABASE_URL from environment, fallback to SQLite if not set
DATABASE_URL = os.getenv("DATABASE_URL")

# For SQLite, need connect_args
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    # Configure schema search path for PostgreSQL connections
    # This ensures all queries use the welcomepage schema by default
    connect_args = {"options": "-csearch_path=welcomepage,public"}
    engine = create_engine(
        DATABASE_URL,
        connect_args=connect_args,
        pool_size=5,          # modest pool to reduce wait timeouts
        max_overflow=5,       # allow short bursts
        pool_pre_ping=True,   # recycle dead/stale connections automatically
        pool_recycle=1800,    # recycle every 30 minutes
        pool_timeout=30       # keep default timeout
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
