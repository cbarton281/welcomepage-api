"""add_sharing_settings_to_team

Revision ID: 20250853
Revises: 20250851
Create Date: 2025-01-22 22:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = '20250853'
down_revision = '20250851'
branch_labels = None
depends_on = None


def upgrade():
    # Add sharing_settings column to teams table
    op.add_column('teams', sa.Column('sharing_settings', JSONB(), nullable=True))


def downgrade():
    # Remove sharing_settings column from teams table
    op.drop_column('teams', 'sharing_settings')

