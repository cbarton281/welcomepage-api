"""Add initiator_public_user_id to slack_state_store

Revision ID: 20250829
Revises: 20250806
Create Date: 2025-08-28 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20250829'
down_revision = '20250827'
branch_labels = None
depends_on = None


def upgrade():
    # Add initiator_public_user_id column to slack_state_store table
    op.add_column('slack_state_store', sa.Column('initiator_public_user_id', sa.String(length=10), nullable=True))

    # Add index for efficient lookups by initiator
    op.create_index(
        'idx_slack_state_store_initiator_public_user_id',
        'slack_state_store',
        ['initiator_public_user_id']
    )


def downgrade():
    # Remove index first
    op.drop_index('idx_slack_state_store_initiator_public_user_id', table_name='slack_state_store')

    # Remove initiator_public_user_id column
    op.drop_column('slack_state_store', 'initiator_public_user_id')
