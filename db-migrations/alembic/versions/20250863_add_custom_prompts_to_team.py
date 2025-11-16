"""add_custom_prompts_to_team

Revision ID: 20250863
Revises: 20250861
Create Date: 2025-01-23 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = '20250863'
down_revision = '20250861'
branch_labels = None
depends_on = None


def upgrade():
    # Add custom_prompts column to teams table
    op.add_column('teams', sa.Column('custom_prompts', JSONB(), nullable=True))


def downgrade():
    # Remove custom_prompts column from teams table
    op.drop_column('teams', 'custom_prompts')

