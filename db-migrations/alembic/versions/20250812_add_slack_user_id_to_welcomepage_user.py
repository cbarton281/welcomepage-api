"""Add slack_user_id to welcomepage_users

Revision ID: 20250812_add_slack_user_id
Revises: 20250807_add_intended_auth_role_to_verification_codes
Create Date: 2025-08-12 10:42:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20250812'
down_revision = '20250807'
branch_labels = None
depends_on = None


def upgrade():
    # Add slack_user_id column to welcomepage_users table
    op.add_column('welcomepage_users', sa.Column('slack_user_id', sa.String(32), nullable=True))
    
    # Add index for efficient Slack user lookups
    op.create_index('idx_welcomepage_users_slack_user_id', 'welcomepage_users', ['slack_user_id'])


def downgrade():
    # Remove index first
    op.drop_index('idx_welcomepage_users_slack_user_id', table_name='welcomepage_users')
    
    # Remove slack_user_id column
    op.drop_column('welcomepage_users', 'slack_user_id')
