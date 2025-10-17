"""Add publish queue fields to welcomepage_users

Revision ID: 20250850
Revises: 20250847
Create Date: 2025-10-16 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20250850'
down_revision = '20250847'
branch_labels = None
depends_on = None


def upgrade():
    # Add publish queue fields to welcomepage_users table
    # These fields track pages that are waiting for payment method to be added
    op.add_column('welcomepage_users', 
                  sa.Column('publish_queued', sa.Boolean(), nullable=False, server_default='0'))
    op.add_column('welcomepage_users', 
                  sa.Column('queued_at', sa.DateTime(), nullable=True))
    
    # Add index for efficient worker queries
    op.create_index('idx_welcomepage_users_publish_queued', 
                    'welcomepage_users', 
                    ['publish_queued', 'team_id'])


def downgrade():
    # Remove index and columns
    op.drop_index('idx_welcomepage_users_publish_queued', table_name='welcomepage_users')
    op.drop_column('welcomepage_users', 'queued_at')
    op.drop_column('welcomepage_users', 'publish_queued')

