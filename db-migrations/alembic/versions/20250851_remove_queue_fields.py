"""remove_queue_fields

Revision ID: 20250851
Revises: 20250850
Create Date: 2025-01-22 20:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20250851'
down_revision = '20250850'
branch_labels = None
depends_on = None


def upgrade():
    # Remove the queue fields from welcomepage_users table
    op.drop_index('idx_welcomepage_users_publish_queued', table_name='welcomepage_users')
    op.drop_column('welcomepage_users', 'queued_at')
    op.drop_column('welcomepage_users', 'publish_queued')


def downgrade():
    # Add the queue fields back if needed
    op.add_column('welcomepage_users', sa.Column('publish_queued', sa.Boolean(), nullable=False, server_default='0'))
    op.add_column('welcomepage_users', sa.Column('queued_at', sa.DateTime(), nullable=True))
    op.create_index('idx_welcomepage_users_publish_queued', 'welcomepage_users', ['publish_queued', 'team_id'])
