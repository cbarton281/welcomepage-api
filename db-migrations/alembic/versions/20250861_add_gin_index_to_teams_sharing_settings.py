"""add_gin_index_to_teams_sharing_settings

Revision ID: 20250861
Revises: 20250860
Create Date: 2025-11-04 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20250861'
down_revision = '20250860'
branch_labels = None
depends_on = None


def upgrade():
    # Create GIN index on teams.sharing_settings for efficient JSONB queries
    # This enables fast lookups on nested JSONB fields like sharing_settings->>'uuid'
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_teams_sharing_settings
        ON teams
        USING GIN (sharing_settings)
    """)


def downgrade():
    # Drop GIN index
    op.execute("DROP INDEX IF EXISTS idx_teams_sharing_settings")

