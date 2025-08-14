"""Add handwave_emoji field to welcomepage_user

Revision ID: 20250813_add_handwave_emoji
Revises: 20250812_add_slack_user_id_to_welcomepage_user
Create Date: 2025-08-13 21:45:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20250813'
down_revision = '20250812'
branch_labels = None
depends_on = None


def upgrade():
    # Add handwave_emoji JSON column to welcomepage_users table
    op.add_column('welcomepage_users', sa.Column('handwave_emoji', sa.JSON(), nullable=True))


def downgrade():
    # Remove handwave_emoji column from welcomepage_users table
    op.drop_column('welcomepage_users', 'handwave_emoji')
