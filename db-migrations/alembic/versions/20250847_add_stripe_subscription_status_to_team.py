"""Add stripe_subscription_status to teams

Revision ID: 20250847
Revises: 20250845
Create Date: 2025-01-15 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20250847'
down_revision = '20250845'
branch_labels = None
depends_on = None


def upgrade():
    # Add stripe_subscription_status column to teams table
    # This stores the raw Stripe subscription status for debugging and detailed user messaging
    op.add_column('teams', sa.Column('stripe_subscription_status', sa.String(50), nullable=True))


def downgrade():
    # Remove stripe_subscription_status column
    op.drop_column('teams', 'stripe_subscription_status')

