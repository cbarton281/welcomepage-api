"""Initial schema and role setup

Revision ID: 20250101
Revises: None
Create Date: 2025-01-01 00:00:00.000000

This migration creates the welcomepage schema and sets up the welcomepagerole
with appropriate permissions. This is safe to run on production as it uses
IF NOT EXISTS checks and idempotent operations.

IMPORTANT: This migration does NOT:
- Set the role password (must be done separately via ALTER ROLE)
- Move existing tables (handled separately if needed)
- Drop any existing data

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20250101'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # 1. Create the welcomepage schema if it doesn't exist
    # This is safe - won't affect existing data
    op.execute("CREATE SCHEMA IF NOT EXISTS welcomepage")
    
    # 1a. If alembic_version table exists in public schema (from first run), move it to welcomepage schema
    # This handles the case where Alembic created the version table in public schema before this migration ran
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = 'alembic_version'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_schema = 'welcomepage' AND table_name = 'alembic_version'
            ) THEN
                ALTER TABLE public.alembic_version SET SCHEMA welcomepage;
            END IF;
        END
        $$;
    """)
    
    # 2. Create the welcomepagerole if it doesn't exist
    # Note: Password must be set separately via: ALTER ROLE welcomepagerole WITH PASSWORD 'password';
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'welcomepagerole') THEN
                CREATE ROLE welcomepagerole WITH LOGIN;
            END IF;
        END
        $$;
    """)
    
    # 3. Grant schema usage to the role
    # These operations are idempotent - safe to run multiple times
    op.execute("GRANT USAGE ON SCHEMA welcomepage TO welcomepagerole")
    
    # 4. Grant privileges on existing tables in the schema (if any)
    op.execute("GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA welcomepage TO welcomepagerole")
    
    # 5. Grant privileges on existing sequences in the schema (if any)
    op.execute("GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA welcomepage TO welcomepagerole")
    
    # 6. Set default privileges for future tables
    op.execute("""
        ALTER DEFAULT PRIVILEGES IN SCHEMA welcomepage 
        GRANT ALL ON TABLES TO welcomepagerole
    """)
    
    # 7. Set default privileges for future sequences
    op.execute("""
        ALTER DEFAULT PRIVILEGES IN SCHEMA welcomepage 
        GRANT ALL ON SEQUENCES TO welcomepagerole
    """)
    
    # 8. Set search path for this session
    # This ensures subsequent operations in this migration use the welcomepage schema
    op.execute("SET search_path TO welcomepage, public")


def downgrade():
    # WARNING: Downgrade will revoke permissions but will NOT drop the schema
    # Dropping the schema would delete all tables and data - too dangerous for automatic rollback
    
    # Revoke default privileges
    op.execute("""
        ALTER DEFAULT PRIVILEGES IN SCHEMA welcomepage 
        REVOKE ALL ON SEQUENCES FROM welcomepagerole
    """)
    op.execute("""
        ALTER DEFAULT PRIVILEGES IN SCHEMA welcomepage 
        REVOKE ALL ON TABLES FROM welcomepagerole
    """)
    
    # Revoke privileges on existing objects
    op.execute("REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA welcomepage FROM welcomepagerole")
    op.execute("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA welcomepage FROM welcomepagerole")
    
    # Revoke schema usage
    op.execute("REVOKE USAGE ON SCHEMA welcomepage FROM welcomepagerole")
    
    # Note: We do NOT drop the role or schema in downgrade to prevent data loss
    # If you need to completely remove, do it manually:
    # DROP SCHEMA IF EXISTS welcomepage CASCADE;
    # DROP ROLE IF EXISTS welcomepagerole;

