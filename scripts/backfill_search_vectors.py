#!/usr/bin/env python3
"""
Script to backfill search_vector column for all existing users in the database.

This script:
1. Connects to the database
2. Iterates through all users
3. Generates and updates their search_vector using the utility function

Usage:
    python scripts/backfill_search_vectors.py

Environment Variables:
    DATABASE_URL: PostgreSQL connection string (optional, can use .env file)
"""

import sys
import os

# Add parent directory to path so we can import from the project
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from models.welcomepage_user import WelcomepageUser
from utils.search_vector import update_search_vector
from utils.logger_factory import new_logger
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = new_logger("backfill_search_vectors")


def get_db_url():
    """Get database URL from environment variables."""
    # Try to construct from individual components first
    db_user = os.getenv("DB_USER", "postgres")
    db_password = os.getenv("DB_PASSWORD", "")
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME", "postgres")
    
    # Or use DATABASE_URL if provided
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url
    
    return f"postgresql+psycopg2://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"


def backfill_search_vectors():
    """Backfill search_vector for all users."""
    db_url = get_db_url()
    logger.info(f"Connecting to database: {db_url.split('@')[1] if '@' in db_url else 'localhost'}")
    
    engine = create_engine(db_url, connect_args={"sslmode": "require"})
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    try:
        # Get all users
        users = db.query(WelcomepageUser).all()
        total_users = len(users)
        logger.info(f"Found {total_users} users to process")
        
        updated_count = 0
        error_count = 0
        
        for i, user in enumerate(users, 1):
            try:
                logger.info(f"Processing user {i}/{total_users}: {user.name} (ID: {user.id}, public_id: {user.public_id})")
                update_search_vector(db, user)
                db.commit()
                updated_count += 1
                
                if i % 100 == 0:
                    logger.info(f"Progress: {i}/{total_users} users processed")
                    
            except Exception as e:
                logger.error(f"Error processing user {user.id} ({user.public_id}): {str(e)}")
                db.rollback()
                error_count += 1
                continue
        
        logger.info(f"Backfill complete!")
        logger.info(f"Successfully updated: {updated_count}")
        logger.info(f"Errors: {error_count}")
        logger.info(f"Total users: {total_users}")
        
    except Exception as e:
        logger.error(f"Fatal error during backfill: {str(e)}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    try:
        backfill_search_vectors()
        print("\n✓ Backfill completed successfully!")
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ Backfill failed: {str(e)}")
        sys.exit(1)

