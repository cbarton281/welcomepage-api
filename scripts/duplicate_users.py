#!/usr/bin/env python3
"""
User Duplication Utility

Creates N duplicate users based on an existing user, with randomly assigned wave GIFs.
Each duplicate gets a unique public_id, realistic name, and a cloned wave GIF from the library.

Usage:
    python duplicate_users.py --user-id <public_id> --count <N>
    
Example:
    python duplicate_users.py --user-id abc123def0 --count 5
"""

import argparse
import random
import requests
import os
import sys
import asyncio
from typing import List, Dict, Any
from faker import Faker
from sqlalchemy.orm import Session

# Add the parent directory to the path so we can import our modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from models.welcomepage_user import WelcomepageUser
from utils.short_id import generate_short_id
from utils.supabase_storage import upload_to_supabase_storage
from utils.logger_factory import new_logger

# Initialize Faker for realistic name generation
fake = Faker()

# Wave GIF library configuration
WAVE_GIF_LIBRARY_BASE_URL = "https://xastkogrfeblbsvmbkew.supabase.co/storage/v1/object/public/test_wave_gif_library"
WAVE_GIF_COUNT = 21  # We have test_wave_gif1.gif through test_wave_gif21.gif

def get_random_wave_gif_url() -> str:
    """Get a random wave GIF URL from the library."""
    gif_number = random.randint(1, WAVE_GIF_COUNT)
    return f"{WAVE_GIF_LIBRARY_BASE_URL}/test_wave_gif{gif_number}.gif"

def download_wave_gif(gif_url: str) -> bytes:
    """Download a wave GIF from the library."""
    log = new_logger("download_wave_gif")
    try:
        response = requests.get(gif_url, timeout=30)
        response.raise_for_status()
        log.info(f"Successfully downloaded wave GIF from {gif_url}")
        return response.content
    except requests.RequestException as e:
        log.error(f"Failed to download wave GIF from {gif_url}: {e}")
        raise

async def clone_wave_gif_to_user(gif_content: bytes, user_public_id: str) -> str:
    """Clone a wave GIF to the user's storage location."""
    log = new_logger("clone_wave_gif_to_user")
    try:
        filename = f"{user_public_id}-wave-gif.gif"
        gif_url = await upload_to_supabase_storage(
            file_content=gif_content,
            filename=filename,
            content_type="image/gif"
        )
        log.info(f"Successfully cloned wave GIF for user {user_public_id}: {gif_url}")
        return gif_url
    except Exception as e:
        log.error(f"Failed to clone wave GIF for user {user_public_id}: {e}")
        raise

def generate_realistic_name() -> str:
    """Generate a realistic name using Faker."""
    return fake.name()

def duplicate_user(original_user: WelcomepageUser, new_public_id: str, new_name: str, wave_gif_url: str) -> WelcomepageUser:
    """Create a duplicate user with new data."""
    log = new_logger("duplicate_user")
    
    # Create a new user object with the same data as the original
    duplicate_data = {
        'public_id': new_public_id,
        'name': new_name,
        'role': original_user.role,
        'location': original_user.location,
        'nickname': original_user.nickname,
        'greeting': original_user.greeting,
        'hi_yall_text': original_user.hi_yall_text,
        'handwave_emoji': original_user.handwave_emoji,
        'handwave_emoji_url': original_user.handwave_emoji_url,
        'profile_photo_url': original_user.profile_photo_url,
        'wave_gif_url': wave_gif_url,  # This is the new cloned GIF URL
        'pronunciation_text': original_user.pronunciation_text,
        'pronunciation_recording_url': original_user.pronunciation_recording_url,
        'selected_prompts': original_user.selected_prompts,
        'answers': original_user.answers,
        'page_comments': original_user.page_comments,
        'bento_widgets': original_user.bento_widgets,
        'invite_banner_dismissed': original_user.invite_banner_dismissed,
        'team_id': original_user.team_id,
        'is_draft': original_user.is_draft,
        'auth_role': original_user.auth_role,
        'auth_email': original_user.auth_email,
        'slack_user_id': None,  # Set to None to avoid unique constraint violation
    }
    
    duplicate_user = WelcomepageUser(**duplicate_data)
    log.info(f"Created duplicate user object: {new_public_id} ({new_name})")
    return duplicate_user

async def main_async():
    parser = argparse.ArgumentParser(description="Duplicate welcomepage users with random wave GIFs")
    parser.add_argument("--user-id", required=True, help="Public ID of the user to duplicate")
    parser.add_argument("--count", type=int, required=True, help="Number of duplicate users to create")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be created without actually creating users")
    
    args = parser.parse_args()
    
    log = new_logger("duplicate_users")
    log.info(f"Starting user duplication: user_id={args.user_id}, count={args.count}, dry_run={args.dry_run}")
    
    # Validate count
    if args.count <= 0:
        log.error("Count must be a positive integer")
        sys.exit(1)
    
    if args.count > 100:
        log.warning(f"Creating {args.count} users - this is a large number. Consider using a smaller batch.")
        response = input("Continue? (y/N): ")
        if response.lower() != 'y':
            log.info("Operation cancelled by user")
            sys.exit(0)
    
    db = SessionLocal()
    try:
        # Find the original user
        original_user = db.query(WelcomepageUser).filter_by(public_id=args.user_id).first()
        if not original_user:
            log.error(f"User with public_id '{args.user_id}' not found")
            sys.exit(1)
        
        log.info(f"Found original user: {original_user.name} (ID: {original_user.id})")
        
        created_users = []
        
        for i in range(args.count):
            log.info(f"Creating duplicate user {i+1}/{args.count}")
            
            # Generate unique public_id
            new_public_id = generate_short_id()
            
            # Generate realistic name
            new_name = generate_realistic_name()
            
            # Get random wave GIF
            wave_gif_url = get_random_wave_gif_url()
            log.info(f"Selected wave GIF: {wave_gif_url}")
            
            if args.dry_run:
                log.info(f"DRY RUN: Would create user {new_public_id} ({new_name}) with wave GIF {wave_gif_url}")
                created_users.append({
                    'public_id': new_public_id,
                    'name': new_name,
                    'wave_gif_url': wave_gif_url
                })
            else:
                # Download and clone the wave GIF
                gif_content = download_wave_gif(wave_gif_url)
                cloned_gif_url = await clone_wave_gif_to_user(gif_content, new_public_id)
                
                # Create duplicate user
                duplicate_user_obj = duplicate_user(original_user, new_public_id, new_name, cloned_gif_url)
                
                # Add to database
                db.add(duplicate_user_obj)
                db.flush()  # Flush to get the ID
                
                created_users.append({
                    'id': duplicate_user_obj.id,
                    'public_id': new_public_id,
                    'name': new_name,
                    'wave_gif_url': cloned_gif_url
                })
                
                log.info(f"Created user {i+1}/{args.count}: {new_public_id} ({new_name})")
        
        if not args.dry_run:
            # Commit all changes
            db.commit()
            log.info(f"Successfully created {args.count} duplicate users")
        else:
            log.info(f"DRY RUN: Would have created {args.count} duplicate users")
        
        # Print summary
        print("\n" + "="*60)
        print("DUPLICATION SUMMARY")
        print("="*60)
        print(f"Original user: {original_user.name} ({original_user.public_id})")
        print(f"Created users: {len(created_users)}")
        print("\nCreated users:")
        for user in created_users:
            print(f"  - {user['name']} ({user['public_id']})")
            if not args.dry_run:
                print(f"    Wave GIF: {user['wave_gif_url']}")
        print("="*60)
        
    except Exception as e:
        log.error(f"Error during user duplication: {e}")
        db.rollback()
        sys.exit(1)
    finally:
        db.close()

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
