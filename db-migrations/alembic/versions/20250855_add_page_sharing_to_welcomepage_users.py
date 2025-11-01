"""add_page_sharing_to_welcomepage_users

Revision ID: 20250855
Revises: 20250853
Create Date: 2025-01-22 23:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20250855'
down_revision = '20250853'
branch_labels = None
depends_on = None


def upgrade():
    # Add share_uuid and is_shareable columns to welcomepage_users table
    op.add_column('welcomepage_users', sa.Column('share_uuid', sa.String(25), nullable=True))
    op.add_column('welcomepage_users', sa.Column('is_shareable', sa.Boolean(), nullable=False, server_default='0'))
    
    # Add index on share_uuid for faster lookups
    op.create_index('idx_welcomepage_users_share_uuid', 'welcomepage_users', ['share_uuid'], unique=True)


def downgrade():
    # Remove index and columns
    op.drop_index('idx_welcomepage_users_share_uuid', table_name='welcomepage_users')
    op.drop_column('welcomepage_users', 'is_shareable')
    op.drop_column('welcomepage_users', 'share_uuid')

