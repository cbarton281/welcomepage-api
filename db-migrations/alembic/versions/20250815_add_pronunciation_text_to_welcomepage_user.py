"""Add pronunciation_text to welcomepage_user

Revision ID: 20250815_add_pronunciation_text
Revises: 20250813_add_handwave_emoji_to_welcomepage_user
Create Date: 2025-08-15 22:24:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20250815'
down_revision = '20250813'
branch_labels = None
depends_on = None


def upgrade():
    # Add pronunciation_text column to welcomepage_users table
    op.add_column('welcomepage_users', sa.Column('pronunciation_text', sa.String(), nullable=True))


def downgrade():
    # Remove pronunciation_text column from welcomepage_users table
    op.drop_column('welcomepage_users', 'pronunciation_text')
