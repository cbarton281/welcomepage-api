"""Add team_public_id to slack_state_store

Revision ID: 20250806
Revises: 20250804_create_slack_state_store
Create Date: 2025-08-04 20:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20250806'
down_revision = '20250804'
branch_labels = None
depends_on = None


def upgrade():
    # Add team_public_id column to slack_state_store table
    op.add_column('slack_state_store', sa.Column('team_public_id', sa.String(length=50), nullable=False))
    
    # Add index for efficient team-based queries
    op.create_index('idx_slack_state_store_team_public_id', 'slack_state_store', ['team_public_id'])


def downgrade():
    # Remove index first
    op.drop_index('idx_slack_state_store_team_public_id', table_name='slack_state_store')
    
    # Remove team_public_id column
    op.drop_column('slack_state_store', 'team_public_id')
