"""add_gin_index_to_teams_slack_settings

Revision ID: 20250860
Revises: 20250859
Create Date: 2025-11-04 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20250860'
down_revision = '20250859'
branch_labels = None
depends_on = None


def upgrade():
    # Create GIN index on teams.slack_settings for efficient JSONB queries
    # This enables fast lookups on nested JSONB fields like slack_settings->'slack_app'->>'team_id'
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_teams_slack_settings
        ON teams
        USING GIN (slack_settings)
    """)


def downgrade():
    # Drop GIN index
    op.execute("DROP INDEX IF EXISTS idx_teams_slack_settings")

