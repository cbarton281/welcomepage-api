"""
Increase initiator_public_user_id column size and add unique index to auth_email

Revision ID: 20250845
Revises: 20250841
Create Date: 2025-01-15 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20250845'
down_revision = '20250841'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Increase the size of initiator_public_user_id column in slack_state_store from 10 to 255 characters
    op.alter_column('slack_state_store', 'initiator_public_user_id',
                    existing_type=sa.String(length=10),
                    type_=sa.String(length=255),
                    existing_nullable=True)
    
    # 2. Add unique index to auth_email in welcomepage_users
    op.create_index('ix_welcomepage_users_auth_email_unique', 'welcomepage_users', ['auth_email'], unique=True)


def downgrade():
    # 1. Remove unique index from auth_email
    op.drop_index('ix_welcomepage_users_auth_email_unique', table_name='welcomepage_users')
    
    # 2. Revert initiator_public_user_id column size back to 10 characters
    op.alter_column('slack_state_store', 'initiator_public_user_id',
                    existing_type=sa.String(length=255),
                    type_=sa.String(length=10),
                    existing_nullable=True)
