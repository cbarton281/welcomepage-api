#!/usr/bin/env python3
"""
Database Copy Script

Copies data from a source database (welcomepage) to the target postgres database/welcomepage schema.

SAFETY: This script is READ-ONLY on the source database. It only performs
SELECT queries to read data. It NEVER modifies, deletes, or updates anything
in the source database. All write operations (INSERT) are performed only
on the target database. Your source database is completely safe.

This script handles:
- Copying all tables in the correct order (respecting foreign key dependencies)
- Mapping IDs if there are conflicts
- Preserving relationships between tables
- Checking for duplicates before inserting (prevents integrity errors)
- Providing progress feedback
- Error handling and rollback on failure

Usage Examples:

    # Method 1: Using full database URLs (recommended for flexibility)
    python copy_database.py \
        --source-db-url "postgresql://user:pass@host:port/welcomepage" \
        --target-db-url "postgresql://user:pass@host:port/postgres"
    
    # Method 2: Using individual connection parameters (user-friendly)
    python copy_database.py \
        --source-host localhost \
        --source-port 5432 \
        --source-user postgres \
        --source-password yourpassword \
        --source-db welcomepage \
        --target-host localhost \
        --target-port 5432 \
        --target-user postgres \
        --target-password yourpassword \
        --target-db postgres
    
    # Method 3: Using environment variables
    SOURCE_DATABASE_URL="postgresql://..." TARGET_DATABASE_URL="postgresql://..." python copy_database.py
    
    # With custom schema names
    python copy_database.py \
        --source-db-url "postgresql://..." \
        --target-db-url "postgresql://..." \
        --source-schema myschema \
        --target-schema welcomepage
    
    # Dry run (see what would be copied without actually copying)
    python copy_database.py --source-db-url "..." --target-db-url "..." --dry-run
"""

import argparse
import os
import sys
from typing import Dict, List, Any, Optional
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, Session, make_transient
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from datetime import datetime
import logging

# Add parent directory to path to import models
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import (
    Team,
    WelcomepageUser,
    VerificationCode,
    PageVisit,
    SlackStateStore,
    SlackPendingInstall
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class DatabaseCopier:
    """Handles copying data from source to target database."""
    
    def __init__(
        self,
        source_db_url: str,
        target_db_url: str,
        source_schema: Optional[str] = None,
        target_schema: str = "welcomepage",
        dry_run: bool = False
    ):
        """
        Initialize the database copier.
        
        Args:
            source_db_url: Connection string for source database
            target_db_url: Connection string for target database
            source_schema: Schema name in source database (None if no schema or using default)
            target_schema: Schema name in target database (default: "welcomepage")
            dry_run: If True, only show what would be copied without actually copying
        """
        self.source_db_url = source_db_url
        self.target_db_url = target_db_url
        self.source_schema = source_schema
        self.target_schema = target_schema
        self.dry_run = dry_run
        
        # Create engines
        self.source_engine = create_engine(source_db_url)
        # Set search path for target to use the specified schema
        search_path = f"{target_schema},public" if target_schema else "public"
        self.target_engine = create_engine(
            target_db_url,
            connect_args={"options": f"-csearch_path={search_path}"}
        )
        
        # Create sessions
        self.source_session = sessionmaker(bind=self.source_engine)()
        self.target_session = sessionmaker(bind=self.target_engine)()
        
        # ID mapping for foreign key relationships
        self.team_id_map: Dict[int, int] = {}
        self.user_id_map: Dict[int, int] = {}
        
        # Statistics
        self.stats = {
            'teams': 0,
            'users': 0,
            'verification_codes': 0,
            'page_visits': 0,
            'slack_state_store': 0,
            'slack_pending_installs': 0,
            'errors': 0
        }
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Clean up sessions."""
        self.source_session.close()
        self.target_session.close()
        self.source_engine.dispose()
        self.target_engine.dispose()
    
    def check_schema_exists(self) -> bool:
        """Check if target schema exists in target database."""
        if not self.target_schema:
            return True  # No schema check needed if using default/public schema
        
        try:
            with self.target_engine.connect() as conn:
                result = conn.execute(text(
                    f"SELECT schema_name FROM information_schema.schemata WHERE schema_name = '{self.target_schema}'"
                ))
                return result.fetchone() is not None
        except Exception as e:
            logger.error(f"Error checking schema: {e}")
            return False
    
    def get_table_count(self, session: Session, model_class, schema: Optional[str] = None) -> int:
        """Get count of records in a table."""
        try:
            if schema:
                # For source database, might not have schema
                query = text(f"SELECT COUNT(*) FROM {schema}.{model_class.__tablename__}")
            else:
                query = text(f"SELECT COUNT(*) FROM {model_class.__tablename__}")
            result = session.execute(query)
            return result.scalar() or 0
        except Exception as e:
            logger.warning(f"Could not get count for {model_class.__tablename__}: {e}")
            return 0
    
    def copy_teams(self) -> bool:
        """Copy teams from source to target."""
        logger.info("Copying teams...")
        try:
            # Try to get teams from source (might be in different schema or no schema)
            source_teams = []
            
            # Models have schema='welcomepage' hardcoded, so skip ORM if source_schema is different
            # or if source_schema is None/public
            use_orm = (self.source_schema is None or self.source_schema == 'welcomepage')
            
            if use_orm:
                try:
                    source_teams = self.source_session.query(Team).all()
                except Exception as e1:
                    logger.warning(f"Could not query Team model directly: {e1}")
                    self.source_session.rollback()  # Rollback after error
                    use_orm = False  # Fall back to raw SQL
            
            if not use_orm:
                # Use raw SQL queries
                try:
                    # Try with schema prefix first (if source_schema is specified)
                    if self.source_schema:
                        result = self.source_session.execute(text(f"SELECT * FROM {self.source_schema}.teams"))
                    else:
                        # Try without schema prefix (public schema or default)
                        result = self.source_session.execute(text("SELECT * FROM teams"))
                    
                    for row in result:
                        team_dict = dict(row._mapping)
                        # Remove id to let database assign new one
                        team_dict.pop('id', None)
                        source_teams.append(Team(**team_dict))
                except Exception as e2:
                    logger.error(f"Could not read teams from source: {e2}")
                    self.source_session.rollback()
                    return False
            
            if not source_teams:
                logger.warning("No teams found in source database")
                return True
            
            logger.info(f"Found {len(source_teams)} teams in source database")
            
            if self.dry_run:
                logger.info(f"[DRY RUN] Would copy {len(source_teams)} teams")
                return True
            
            for source_team in source_teams:
                try:
                    # Check if team already exists by public_id
                    existing = self.target_session.query(Team).filter(
                        Team.public_id == source_team.public_id
                    ).first()
                    
                    if existing:
                        logger.warning(f"Team with public_id {source_team.public_id} already exists, skipping")
                        self.team_id_map[source_team.id] = existing.id
                        continue
                    
                    # Create new team
                    new_team = Team(
                        public_id=source_team.public_id,
                        organization_name=source_team.organization_name,
                        company_logo_url=source_team.company_logo_url,
                        color_scheme=source_team.color_scheme,
                        color_scheme_data=source_team.color_scheme_data,
                        slack_settings=source_team.slack_settings,
                        security_settings=source_team.security_settings,
                        sharing_settings=source_team.sharing_settings,
                        custom_prompts=source_team.custom_prompts,
                        is_draft=source_team.is_draft,
                        stripe_customer_id=source_team.stripe_customer_id,
                        stripe_subscription_id=source_team.stripe_subscription_id,
                        stripe_subscription_status=source_team.stripe_subscription_status,
                        subscription_status=source_team.subscription_status
                    )
                    
                    self.target_session.add(new_team)
                    self.target_session.flush()  # Get the new ID
                    
                    # Map old ID to new ID
                    self.team_id_map[source_team.id] = new_team.id
                    self.stats['teams'] += 1
                    
                except IntegrityError as e:
                    logger.error(f"Error copying team {source_team.public_id}: {e}")
                    self.stats['errors'] += 1
                    self.target_session.rollback()
                    continue
                except Exception as e:
                    logger.error(f"Unexpected error copying team {source_team.id}: {e}")
                    self.stats['errors'] += 1
                    self.target_session.rollback()
                    continue
            
            self.target_session.commit()
            logger.info(f"Successfully copied {self.stats['teams']} teams")
            return True
            
        except Exception as e:
            logger.error(f"Error in copy_teams: {e}")
            self.target_session.rollback()
            return False
    
    def copy_users(self) -> bool:
        """Copy users from source to target."""
        logger.info("Copying users...")
        try:
            source_users = []
            
            # Models have schema='welcomepage' hardcoded, so skip ORM if source_schema is different
            use_orm = (self.source_schema is None or self.source_schema == 'welcomepage')
            
            if use_orm:
                try:
                    source_users = self.source_session.query(WelcomepageUser).all()
                except Exception as e1:
                    logger.warning(f"Could not query WelcomepageUser model directly: {e1}")
                    self.source_session.rollback()  # Rollback after error
                    use_orm = False  # Fall back to raw SQL
            
            if not use_orm:
                # Use raw SQL queries
                try:
                    # Try with schema prefix first (if source_schema is specified)
                    if self.source_schema:
                        result = self.source_session.execute(text(f"SELECT * FROM {self.source_schema}.welcomepage_users"))
                    else:
                        # Try without schema prefix (public schema or default)
                        result = self.source_session.execute(text("SELECT * FROM welcomepage_users"))
                    
                    for row in result:
                        user_dict = dict(row._mapping)
                        # Preserve the original team_id before removing id
                        original_team_id = user_dict.get('team_id')
                        user_dict.pop('id', None)
                        # Create instance - team_id should be in user_dict if it was in the row
                        user_instance = WelcomepageUser(**user_dict)
                        # Explicitly set team_id to ensure it's preserved (in case it was None in dict)
                        if original_team_id is not None:
                            user_instance.team_id = original_team_id
                        # Verify team_id is set
                        if original_team_id is not None and user_instance.team_id != original_team_id:
                            logger.warning(f"Warning: team_id mismatch for user {user_dict.get('public_id')}: expected {original_team_id}, got {user_instance.team_id}")
                        source_users.append(user_instance)
                except Exception as e2:
                    logger.error(f"Could not read users from source: {e2}")
                    self.source_session.rollback()
                    return False
            
            if not source_users:
                logger.warning("No users found in source database")
                return True
            
            logger.info(f"Found {len(source_users)} users in source database")
            
            if self.dry_run:
                logger.info(f"[DRY RUN] Would copy {len(source_users)} users")
                return True
            
            for source_user in source_users:
                try:
                    # Check if user already exists by public_id
                    existing = self.target_session.query(WelcomepageUser).filter(
                        WelcomepageUser.public_id == source_user.public_id
                    ).first()
                    
                    # Map team_id if it exists (needed for both new and existing users)
                    new_team_id = None
                    original_team_id = getattr(source_user, 'team_id', None)
                    
                    if original_team_id is not None:
                        if original_team_id in self.team_id_map:
                            new_team_id = self.team_id_map[original_team_id]
                            logger.debug(f"Mapping user {source_user.public_id} team_id {original_team_id} -> {new_team_id}")
                        else:
                            # Try to find team by looking up the source team's public_id
                            # This handles the case where teams already exist in target
                            source_team = None
                            try:
                                # Try to get the source team to find its public_id
                                if use_orm:
                                    # If we used ORM, we can't easily get the source team
                                    # But we should have the mapping already
                                    pass
                                else:
                                    # Query source database to get team's public_id
                                    schema_prefix = f"{self.source_schema}." if self.source_schema else ""
                                    team_result = self.source_session.execute(
                                        text(f"SELECT public_id FROM {schema_prefix}teams WHERE id = :team_id"),
                                        {'team_id': original_team_id}
                                    ).first()
                                    if team_result:
                                        source_team_public_id = team_result[0]
                                        # Find the team in target by public_id
                                        target_team = self.target_session.query(Team).filter(
                                            Team.public_id == source_team_public_id
                                        ).first()
                                        if target_team:
                                            new_team_id = target_team.id
                                            # Add to map for future use
                                            self.team_id_map[original_team_id] = target_team.id
                                            logger.info(f"Found team by public_id {source_team_public_id}, mapping user {source_user.public_id} team_id {original_team_id} -> {new_team_id}")
                            except Exception as lookup_error:
                                logger.debug(f"Could not lookup team for user {source_user.public_id}: {lookup_error}")
                            
                            if new_team_id is None:
                                logger.warning(f"User {source_user.public_id} has team_id {original_team_id} that doesn't exist in target team_id_map (map has {len(self.team_id_map)} entries), setting to None")
                    else:
                        logger.debug(f"User {source_user.public_id} has no team_id in source")
                    
                    # If user already exists, update team_id if needed
                    if existing:
                        self.user_id_map[source_user.id] = existing.id
                        
                        # Query the actual database value directly to avoid any ORM caching issues
                        actual_team_id_result = self.target_session.execute(
                            text(f"SELECT team_id FROM {self.target_schema}.welcomepage_users WHERE public_id = :public_id"),
                            {'public_id': source_user.public_id}
                        ).scalar()
                        actual_team_id = actual_team_id_result
                        
                        # Debug logging
                        logger.info(f"Existing user {source_user.public_id}: source_team_id={original_team_id}, mapped_team_id={new_team_id}, actual_db_team_id={actual_team_id}")
                        
                        # Update team_id if it's null or different - use direct SQL UPDATE to ensure it works
                        if original_team_id is not None and new_team_id is not None:
                            if actual_team_id != new_team_id:
                                logger.info(f"Updating existing user {source_user.public_id} team_id from {actual_team_id} to {new_team_id} using direct SQL")
                                # Use direct SQL UPDATE to bypass any ORM issues
                                update_stmt = text(f"""
                                    UPDATE {self.target_schema}.welcomepage_users 
                                    SET team_id = :team_id 
                                    WHERE public_id = :public_id
                                """)
                                self.target_session.execute(update_stmt, {
                                    'team_id': new_team_id,
                                    'public_id': source_user.public_id
                                })
                                # Force flush to ensure change is tracked
                                self.target_session.flush()
                                # Track that we updated this user
                                if 'users_updated' not in self.stats:
                                    self.stats['users_updated'] = 0
                                self.stats['users_updated'] += 1
                            else:
                                logger.debug(f"Existing user {source_user.public_id} already has correct team_id {new_team_id}")
                        elif original_team_id is not None and new_team_id is None:
                            logger.warning(f"Existing user {source_user.public_id} has source team_id {original_team_id} but could not map to target team_id")
                        elif original_team_id is None:
                            logger.debug(f"Existing user {source_user.public_id} has no team_id in source, leaving actual_db_team_id={actual_team_id} unchanged")
                        continue
                    
                    # Create new user
                    # Log team_id mapping for debugging
                    if original_team_id is not None and new_team_id is None:
                        logger.warning(f"WARNING: User {source_user.public_id} has source team_id {original_team_id} but mapping resulted in None!")
                    elif original_team_id is not None and new_team_id is not None:
                        logger.debug(f"User {source_user.public_id}: team_id {original_team_id} -> {new_team_id}")
                    
                    new_user = WelcomepageUser(
                        public_id=source_user.public_id,
                        name=source_user.name,
                        role=source_user.role,
                        location=source_user.location,
                        nickname=source_user.nickname,
                        greeting=source_user.greeting,
                        hi_yall_text=source_user.hi_yall_text,
                        handwave_emoji=source_user.handwave_emoji,
                        handwave_emoji_url=source_user.handwave_emoji_url,
                        profile_photo_url=source_user.profile_photo_url,
                        wave_gif_url=source_user.wave_gif_url,
                        pronunciation_text=source_user.pronunciation_text,
                        pronunciation_recording_url=source_user.pronunciation_recording_url,
                        selected_prompts=source_user.selected_prompts,
                        answers=source_user.answers,
                        page_comments=source_user.page_comments,
                        bento_widgets=source_user.bento_widgets,
                        invite_banner_dismissed=source_user.invite_banner_dismissed,
                        team_id=new_team_id,  # This should be set from the mapping above
                        is_draft=source_user.is_draft,
                        auth_role=source_user.auth_role,
                        auth_email=source_user.auth_email,
                        slack_user_id=source_user.slack_user_id,
                        is_shareable=source_user.is_shareable,
                        share_uuid=source_user.share_uuid,
                        created_at=source_user.created_at,
                        updated_at=source_user.updated_at
                    )
                    
                    # Double-check team_id is set correctly and fix if needed
                    if original_team_id is not None:
                        if new_team_id is None:
                            logger.error(f"ERROR: User {source_user.public_id} has source team_id {original_team_id} but mapping resulted in None!")
                        elif new_user.team_id != new_team_id:
                            logger.warning(f"WARNING: team_id mismatch for user {source_user.public_id}: expected {new_team_id}, got {new_user.team_id}, fixing...")
                            new_user.team_id = new_team_id  # Explicitly set it
                        else:
                            logger.debug(f"Verified: User {source_user.public_id} team_id correctly set to {new_team_id}")
                    else:
                        # If source had no team_id, ensure target also has None (explicit)
                        if new_user.team_id is not None:
                            logger.warning(f"WARNING: User {source_user.public_id} had no team_id in source but target has {new_user.team_id}, setting to None")
                            new_user.team_id = None
                    
                    # Final verification before adding to session
                    if original_team_id is not None and new_team_id is not None:
                        if new_user.team_id != new_team_id:
                            logger.error(f"CRITICAL: User {source_user.public_id} team_id is {new_user.team_id} but should be {new_team_id}, forcing update")
                            new_user.team_id = new_team_id
                    
                    self.target_session.add(new_user)
                    self.target_session.flush()  # Get the new ID
                    
                    # Map old ID to new ID
                    self.user_id_map[source_user.id] = new_user.id
                    self.stats['users'] += 1
                    
                except IntegrityError as e:
                    logger.error(f"Error copying user {source_user.public_id}: {e}")
                    self.stats['errors'] += 1
                    self.target_session.rollback()
                    continue
                except Exception as e:
                    logger.error(f"Unexpected error copying user {source_user.id}: {e}")
                    self.stats['errors'] += 1
                    self.target_session.rollback()
                    continue
            
            self.target_session.commit()
            updated_count = self.stats.get('users_updated', 0)
            if updated_count > 0:
                logger.info(f"Successfully copied {self.stats['users']} new users and updated {updated_count} existing users' team_id")
            else:
                logger.info(f"Successfully copied {self.stats['users']} users")
            return True
            
        except Exception as e:
            logger.error(f"Error in copy_users: {e}")
            self.target_session.rollback()
            return False
    
    def copy_verification_codes(self) -> bool:
        """Copy verification codes from source to target."""
        logger.info("Copying verification codes...")
        try:
            source_codes = []
            
            # Models have schema='welcomepage' hardcoded, so skip ORM if source_schema is different
            use_orm = (self.source_schema is None or self.source_schema == 'welcomepage')
            
            if use_orm:
                try:
                    source_codes = self.source_session.query(VerificationCode).all()
                except Exception as e1:
                    logger.warning(f"Could not query VerificationCode model directly: {e1}")
                    self.source_session.rollback()  # Rollback after error
                    use_orm = False  # Fall back to raw SQL
            
            if not use_orm:
                # Use raw SQL queries
                try:
                    # Try with schema prefix first (if source_schema is specified)
                    if self.source_schema:
                        result = self.source_session.execute(text(f"SELECT * FROM {self.source_schema}.verification_codes"))
                    else:
                        # Try without schema prefix (public schema or default)
                        result = self.source_session.execute(text("SELECT * FROM verification_codes"))
                    
                    for row in result:
                        code_dict = dict(row._mapping)
                        code_dict.pop('id', None)
                        source_codes.append(VerificationCode(**code_dict))
                except Exception as e2:
                    logger.error(f"Could not read verification codes from source: {e2}")
                    self.source_session.rollback()
                    return False
            
            if not source_codes:
                logger.info("No verification codes found in source database")
                return True
            
            logger.info(f"Found {len(source_codes)} verification codes in source database")
            
            if self.dry_run:
                logger.info(f"[DRY RUN] Would copy {len(source_codes)} verification codes")
                return True
            
            for source_code in source_codes:
                try:
                    # Check if code already exists by public_id (more reliable than id for reentrancy)
                    existing = None
                    if source_code.public_id:
                        existing = self.target_session.query(VerificationCode).filter(
                            VerificationCode.public_id == source_code.public_id
                        ).first()
                    # Fallback to checking by email+code if no public_id
                    if not existing and source_code.email and source_code.code:
                        existing = self.target_session.query(VerificationCode).filter(
                            VerificationCode.email == source_code.email,
                            VerificationCode.code == source_code.code
                        ).first()
                    
                    if existing:
                        continue
                    
                    new_code = VerificationCode(
                        email=source_code.email,
                        code=source_code.code,
                        created_at=source_code.created_at,
                        expires_at=source_code.expires_at,
                        used=source_code.used,
                        public_id=source_code.public_id,
                        intended_auth_role=source_code.intended_auth_role
                    )
                    
                    self.target_session.add(new_code)
                    self.stats['verification_codes'] += 1
                    
                except IntegrityError as e:
                    logger.warning(f"Error copying verification code {source_code.id}: {e}")
                    self.stats['errors'] += 1
                    continue
                except Exception as e:
                    logger.warning(f"Unexpected error copying verification code {source_code.id}: {e}")
                    self.stats['errors'] += 1
                    continue
            
            self.target_session.commit()
            logger.info(f"Successfully copied {self.stats['verification_codes']} verification codes")
            return True
            
        except Exception as e:
            logger.error(f"Error in copy_verification_codes: {e}")
            self.target_session.rollback()
            return False
    
    def copy_page_visits(self) -> bool:
        """Copy page visits from source to target."""
        logger.info("Copying page visits...")
        try:
            source_visits = []
            
            # Models have schema='welcomepage' hardcoded, so skip ORM if source_schema is different
            use_orm = (self.source_schema is None or self.source_schema == 'welcomepage')
            
            if use_orm:
                try:
                    source_visits = self.source_session.query(PageVisit).all()
                except Exception as e1:
                    logger.warning(f"Could not query PageVisit model directly: {e1}")
                    self.source_session.rollback()  # Rollback after error
                    use_orm = False  # Fall back to raw SQL
            
            if not use_orm:
                # Use raw SQL queries
                try:
                    # Try with schema prefix first (if source_schema is specified)
                    if self.source_schema:
                        result = self.source_session.execute(text(f"SELECT * FROM {self.source_schema}.page_visits"))
                    else:
                        # Try without schema prefix (public schema or default)
                        result = self.source_session.execute(text("SELECT * FROM page_visits"))
                    
                    for row in result:
                        visit_dict = dict(row._mapping)
                        visit_dict.pop('id', None)
                        source_visits.append(PageVisit(**visit_dict))
                except Exception as e2:
                    logger.error(f"Could not read page visits from source: {e2}")
                    self.source_session.rollback()
                    return False
            
            if not source_visits:
                logger.info("No page visits found in source database")
                return True
            
            logger.info(f"Found {len(source_visits)} page visits in source database")
            
            if self.dry_run:
                logger.info(f"[DRY RUN] Would copy {len(source_visits)} page visits")
                return True
            
            skipped_count = 0
            for source_visit in source_visits:
                try:
                    # Map visited_user_id if it exists
                    new_visited_user_id = source_visit.visited_user_id
                    if source_visit.visited_user_id in self.user_id_map:
                        new_visited_user_id = self.user_id_map[source_visit.visited_user_id]
                    
                    # Check if visit already exists (check by visited_user_id, visitor_public_id, and visit_start_time)
                    # This combination should uniquely identify a visit
                    # Use a small time window tolerance (1 second) for visit_start_time comparison
                    # since datetime precision might differ slightly
                    visit_start = source_visit.visit_start_time
                    existing = None
                    if visit_start:
                        # Check for exact match first
                        existing = self.target_session.query(PageVisit).filter(
                            PageVisit.visited_user_id == new_visited_user_id,
                            PageVisit.visitor_public_id == source_visit.visitor_public_id,
                            PageVisit.visit_start_time == visit_start
                        ).first()
                    
                    if existing:
                        skipped_count += 1
                        continue  # Skip duplicate visit
                    
                    new_visit = PageVisit(
                        visited_user_id=new_visited_user_id,
                        visitor_public_id=source_visit.visitor_public_id,
                        visit_start_time=source_visit.visit_start_time,
                        visit_end_time=source_visit.visit_end_time,
                        visit_duration_seconds=source_visit.visit_duration_seconds,
                        visitor_country=source_visit.visitor_country,
                        visitor_region=source_visit.visitor_region,
                        visitor_city=source_visit.visitor_city,
                        referrer=source_visit.referrer,
                        user_agent=source_visit.user_agent,
                        session_id=source_visit.session_id,
                        created_at=source_visit.created_at
                    )
                    
                    self.target_session.add(new_visit)
                    self.stats['page_visits'] += 1
                    
                except IntegrityError as e:
                    logger.warning(f"Error copying page visit (likely duplicate): {e}")
                    self.stats['errors'] += 1
                    continue
                except Exception as e:
                    logger.warning(f"Error copying page visit {source_visit.id}: {e}")
                    self.stats['errors'] += 1
                    continue
            
            self.target_session.commit()
            if skipped_count > 0:
                logger.info(f"Skipped {skipped_count} duplicate page visits")
            logger.info(f"Successfully copied {self.stats['page_visits']} page visits")
            return True
            
        except Exception as e:
            logger.error(f"Error in copy_page_visits: {e}")
            self.target_session.rollback()
            return False
    
    def copy_slack_state_store(self) -> bool:
        """Copy Slack state store from source to target."""
        logger.info("Copying Slack state store...")
        try:
            source_states = []
            
            # Models have schema='welcomepage' hardcoded, so skip ORM if source_schema is different
            use_orm = (self.source_schema is None or self.source_schema == 'welcomepage')
            
            if use_orm:
                try:
                    orm_states = self.source_session.query(SlackStateStore).all()
                    # Convert ORM instances to dicts to avoid session attachment issues
                    source_states = []
                    for state in orm_states:
                        source_states.append({
                            'state': state.state,
                            'team_public_id': state.team_public_id,
                            'initiator_public_user_id': state.initiator_public_user_id,
                            'created_at': state.created_at,
                            'expires_at': state.expires_at,
                            'consumed': state.consumed
                        })
                except Exception as e1:
                    logger.warning(f"Could not query SlackStateStore model directly: {e1}")
                    self.source_session.rollback()  # Rollback after error
                    use_orm = False  # Fall back to raw SQL
            
            if not use_orm:
                # Use raw SQL queries - store as dicts to avoid SQLAlchemy state issues
                try:
                    # Try with schema prefix first (if source_schema is specified)
                    if self.source_schema:
                        result = self.source_session.execute(text(f"SELECT * FROM {self.source_schema}.slack_state_store"))
                    else:
                        # Try without schema prefix (public schema or default)
                        result = self.source_session.execute(text("SELECT * FROM slack_state_store"))
                    
                    for row in result:
                        state_dict = dict(row._mapping)
                        state_dict.pop('id', None)
                        # Store as dict - we'll create proper instances when copying to target
                        source_states.append(state_dict)
                except Exception as e2:
                    logger.error(f"Could not read slack state store from source: {e2}")
                    self.source_session.rollback()
                    return False
            
            if not source_states:
                logger.info("No Slack state store records found in source database")
                return True
            
            logger.info(f"Found {len(source_states)} Slack state store records in source database")
            
            if self.dry_run:
                logger.info(f"[DRY RUN] Would copy {len(source_states)} Slack state store records")
                return True
            
            for state_data in source_states:
                try:
                    state_value = state_data.get('state')
                    
                    # Check if state already exists
                    existing = self.target_session.query(SlackStateStore).filter(
                        SlackStateStore.state == state_value
                    ).first()
                    
                    if existing:
                        continue
                    
                    # Use raw SQL INSERT to avoid ORM instance state issues
                    # This bypasses the custom __init__ method entirely
                    insert_stmt = text(f"""
                        INSERT INTO {self.target_schema}.slack_state_store 
                        (state, team_public_id, initiator_public_user_id, created_at, expires_at, consumed)
                        VALUES (:state, :team_public_id, :initiator_public_user_id, :created_at, :expires_at, :consumed)
                    """)
                    
                    self.target_session.execute(insert_stmt, {
                        'state': state_data['state'],
                        'team_public_id': state_data['team_public_id'],
                        'initiator_public_user_id': state_data.get('initiator_public_user_id'),
                        'created_at': state_data['created_at'],
                        'expires_at': state_data['expires_at'],
                        'consumed': state_data.get('consumed', False)
                    })
                    self.stats['slack_state_store'] += 1
                    
                except IntegrityError as e:
                    logger.warning(f"Error copying Slack state {state_data.get('state', 'unknown')}: {e}")
                    self.stats['errors'] += 1
                    continue
                except Exception as e:
                    logger.warning(f"Unexpected error copying Slack state {state_data.get('state', 'unknown')}: {e}")
                    self.stats['errors'] += 1
                    continue
            
            self.target_session.commit()
            logger.info(f"Successfully copied {self.stats['slack_state_store']} Slack state store records")
            return True
            
        except Exception as e:
            logger.error(f"Error in copy_slack_state_store: {e}")
            self.target_session.rollback()
            return False
    
    def copy_slack_pending_installs(self) -> bool:
        """Copy Slack pending installs from source to target."""
        logger.info("Copying Slack pending installs...")
        try:
            source_installs = []
            
            # Models have schema='welcomepage' hardcoded, so skip ORM if source_schema is different
            use_orm = (self.source_schema is None or self.source_schema == 'welcomepage')
            
            if use_orm:
                try:
                    orm_installs = self.source_session.query(SlackPendingInstall).all()
                    # Convert ORM instances to dicts to avoid session attachment issues
                    source_installs = []
                    for install in orm_installs:
                        source_installs.append({
                            'nonce': install.nonce,
                            'slack_team_id': install.slack_team_id,
                            'slack_team_name': install.slack_team_name,
                            'slack_user_id': install.slack_user_id,
                            'installation_json': install.installation_json,
                            'created_at': install.created_at,
                            'expires_at': install.expires_at,
                            'consumed': install.consumed
                        })
                except Exception as e1:
                    logger.warning(f"Could not query SlackPendingInstall model directly: {e1}")
                    self.source_session.rollback()  # Rollback after error
                    use_orm = False  # Fall back to raw SQL
            
            if not use_orm:
                # Use raw SQL queries - store as dicts to avoid SQLAlchemy state issues
                try:
                    # Try with schema prefix first (if source_schema is specified)
                    if self.source_schema:
                        result = self.source_session.execute(text(f"SELECT * FROM {self.source_schema}.slack_pending_installs"))
                    else:
                        # Try without schema prefix (public schema or default)
                        result = self.source_session.execute(text("SELECT * FROM slack_pending_installs"))
                    
                    for row in result:
                        install_dict = dict(row._mapping)
                        install_dict.pop('id', None)
                        # Store as dict - we'll create proper instances when copying to target
                        source_installs.append(install_dict)
                except Exception as e2:
                    logger.error(f"Could not read slack pending installs from source: {e2}")
                    self.source_session.rollback()
                    return False
            
            if not source_installs:
                logger.info("No Slack pending installs found in source database")
                return True
            
            logger.info(f"Found {len(source_installs)} Slack pending installs in source database")
            
            if self.dry_run:
                logger.info(f"[DRY RUN] Would copy {len(source_installs)} Slack pending installs")
                return True
            
            for install_data in source_installs:
                try:
                    nonce_value = install_data.get('nonce')
                    
                    # Check if install already exists
                    existing = self.target_session.query(SlackPendingInstall).filter(
                        SlackPendingInstall.nonce == nonce_value
                    ).first()
                    
                    if existing:
                        continue
                    
                    # Use raw SQL INSERT to avoid ORM instance state issues
                    # This bypasses the custom __init__ method entirely
                    import json
                    from sqlalchemy.dialects.postgresql import JSONB
                    
                    # Convert installation_json to JSON string if it's a dict
                    installation_json = install_data['installation_json']
                    if isinstance(installation_json, dict):
                        installation_json = json.dumps(installation_json)
                    elif installation_json is None:
                        installation_json = '{}'  # Default to empty JSON object
                    
                    # Use CAST for JSONB instead of ::jsonb syntax to avoid parameter style conflicts
                    insert_stmt = text(f"""
                        INSERT INTO {self.target_schema}.slack_pending_installs 
                        (nonce, slack_team_id, slack_team_name, slack_user_id, installation_json, created_at, expires_at, consumed)
                        VALUES (:nonce, :slack_team_id, :slack_team_name, :slack_user_id, CAST(:installation_json AS jsonb), :created_at, :expires_at, :consumed)
                    """)
                    
                    self.target_session.execute(insert_stmt, {
                        'nonce': install_data['nonce'],
                        'slack_team_id': install_data.get('slack_team_id'),
                        'slack_team_name': install_data.get('slack_team_name'),
                        'slack_user_id': install_data.get('slack_user_id'),
                        'installation_json': installation_json,
                        'created_at': install_data['created_at'],
                        'expires_at': install_data['expires_at'],
                        'consumed': install_data.get('consumed', False)
                    })
                    self.stats['slack_pending_installs'] += 1
                    
                except IntegrityError as e:
                    logger.warning(f"Error copying Slack pending install {install_data.get('nonce', 'unknown')}: {e}")
                    self.stats['errors'] += 1
                    continue
                except Exception as e:
                    logger.warning(f"Unexpected error copying Slack pending install {install_data.get('nonce', 'unknown')}: {e}")
                    self.stats['errors'] += 1
                    continue
            
            self.target_session.commit()
            logger.info(f"Successfully copied {self.stats['slack_pending_installs']} Slack pending installs")
            return True
            
        except Exception as e:
            logger.error(f"Error in copy_slack_pending_installs: {e}")
            self.target_session.rollback()
            return False
    
    def copy_all(self) -> bool:
        """Copy all data from source to target in the correct order."""
        logger.info("Starting database copy operation...")
        logger.info(f"Source: {self.source_db_url.split('@')[-1] if '@' in self.source_db_url else 'hidden'}")
        logger.info(f"Target: {self.target_db_url.split('@')[-1] if '@' in self.target_db_url else 'hidden'}")
        
        if not self.check_schema_exists():
            schema_name = self.target_schema or "public"
            logger.error(f"Target database does not have '{schema_name}' schema. Please create it first.")
            if self.target_schema:
                logger.error("Run: cd db-migrations && alembic upgrade head")
            return False
        
        # Copy in dependency order
        steps = [
            ("Teams", self.copy_teams),
            ("Users", self.copy_users),
            ("Verification Codes", self.copy_verification_codes),
            ("Page Visits", self.copy_page_visits),
            ("Slack State Store", self.copy_slack_state_store),
            ("Slack Pending Installs", self.copy_slack_pending_installs),
        ]
        
        for step_name, step_func in steps:
            logger.info(f"\n{'='*60}")
            logger.info(f"Step: {step_name}")
            logger.info(f"{'='*60}")
            
            if not step_func():
                logger.error(f"Failed to copy {step_name}")
                return False
        
        # Print summary
        logger.info(f"\n{'='*60}")
        logger.info("Copy Summary")
        logger.info(f"{'='*60}")
        logger.info(f"Teams: {self.stats['teams']}")
        logger.info(f"Users: {self.stats['users']}")
        logger.info(f"Verification Codes: {self.stats['verification_codes']}")
        logger.info(f"Page Visits: {self.stats['page_visits']}")
        logger.info(f"Slack State Store: {self.stats['slack_state_store']}")
        logger.info(f"Slack Pending Installs: {self.stats['slack_pending_installs']}")
        logger.info(f"Errors: {self.stats['errors']}")
        logger.info(f"{'='*60}\n")
        
        return True


def build_db_url(host: str, port: str, user: str, password: str, db: str) -> str:
    """Build a PostgreSQL connection URL from individual parameters."""
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"


def get_env_or_default(key: str, default: str = "") -> str:
    """Get environment variable or return default."""
    return os.getenv(key, default)


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Copy data from source database to target postgres database/welcomepage schema"
    )
    
    # Full URL method (Method 1)
    parser.add_argument(
        "--source-db-url",
        type=str,
        help="Source database connection URL (e.g., postgresql://user:pass@host:port/welcomepage)",
        default=os.getenv("SOURCE_DATABASE_URL")
    )
    parser.add_argument(
        "--target-db-url",
        type=str,
        help="Target database connection URL (e.g., postgresql://user:pass@host:port/postgres)",
        default=os.getenv("TARGET_DATABASE_URL")
    )
    
    # Individual parameters method (Method 2) - Source
    parser.add_argument(
        "--source-host",
        type=str,
        default=get_env_or_default("SOURCE_DB_HOST", "localhost"),
        help="Source database host (default: localhost or SOURCE_DB_HOST env var)"
    )
    parser.add_argument(
        "--source-port",
        type=str,
        default=get_env_or_default("SOURCE_DB_PORT", "5432"),
        help="Source database port (default: 5432 or SOURCE_DB_PORT env var)"
    )
    parser.add_argument(
        "--source-user",
        type=str,
        default=get_env_or_default("SOURCE_DB_USER", "postgres"),
        help="Source database user (default: postgres or SOURCE_DB_USER env var)"
    )
    parser.add_argument(
        "--source-password",
        type=str,
        default=get_env_or_default("SOURCE_DB_PASSWORD", ""),
        help="Source database password (default: SOURCE_DB_PASSWORD env var)"
    )
    parser.add_argument(
        "--source-db",
        type=str,
        default=get_env_or_default("SOURCE_DB_NAME", "welcomepage"),
        help="Source database name (default: welcomepage or SOURCE_DB_NAME env var)"
    )
    
    # Individual parameters method (Method 2) - Target
    parser.add_argument(
        "--target-host",
        type=str,
        default=get_env_or_default("TARGET_DB_HOST", "localhost"),
        help="Target database host (default: localhost or TARGET_DB_HOST env var)"
    )
    parser.add_argument(
        "--target-port",
        type=str,
        default=get_env_or_default("TARGET_DB_PORT", "5432"),
        help="Target database port (default: 5432 or TARGET_DB_PORT env var)"
    )
    parser.add_argument(
        "--target-user",
        type=str,
        default=get_env_or_default("TARGET_DB_USER", "postgres"),
        help="Target database user (default: postgres or TARGET_DB_USER env var)"
    )
    parser.add_argument(
        "--target-password",
        type=str,
        default=get_env_or_default("TARGET_DB_PASSWORD", ""),
        help="Target database password (default: TARGET_DB_PASSWORD env var)"
    )
    parser.add_argument(
        "--target-db",
        type=str,
        default=get_env_or_default("TARGET_DB_NAME", "postgres"),
        help="Target database name (default: postgres or TARGET_DB_NAME env var)"
    )
    
    # Schema parameters
    parser.add_argument(
        "--source-schema",
        type=str,
        default=get_env_or_default("SOURCE_DB_SCHEMA", None),
        help="Source database schema name (default: None or SOURCE_DB_SCHEMA env var). Use if source tables are in a specific schema."
    )
    parser.add_argument(
        "--target-schema",
        type=str,
        default=get_env_or_default("TARGET_DB_SCHEMA", "welcomepage"),
        help="Target database schema name (default: welcomepage or TARGET_DB_SCHEMA env var)"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be copied without actually copying"
    )
    
    args = parser.parse_args()
    
    # Determine which method to use: full URL or individual parameters
    source_db_url = args.source_db_url
    target_db_url = args.target_db_url
    
    # If full URLs not provided, build from individual parameters
    if not source_db_url:
        if not args.source_password:
            logger.error("Source database password is required. Use --source-password or set SOURCE_DB_PASSWORD environment variable.")
            sys.exit(1)
        source_db_url = build_db_url(
            args.source_host,
            args.source_port,
            args.source_user,
            args.source_password,
            args.source_db
        )
    
    if not target_db_url:
        if not args.target_password:
            logger.error("Target database password is required. Use --target-password or set TARGET_DB_PASSWORD environment variable.")
            sys.exit(1)
        target_db_url = build_db_url(
            args.target_host,
            args.target_port,
            args.target_user,
            args.target_password,
            args.target_db
        )
    
    try:
        with DatabaseCopier(
            source_db_url,
            target_db_url,
            source_schema=args.source_schema,
            target_schema=args.target_schema,
            dry_run=args.dry_run
        ) as copier:
            success = copier.copy_all()
            sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.info("\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

