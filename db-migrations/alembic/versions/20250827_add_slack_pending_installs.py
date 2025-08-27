"""
add slack_pending_installs table

Revision ID: 20250827_add_slack_pending_installs
Revises: 20250825
Create Date: 2025-08-27 12:30:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20250827'
down_revision = '20250825'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'slack_pending_installs',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('nonce', sa.String(length=255), nullable=False),
        sa.Column('slack_team_id', sa.String(length=32), nullable=True),
        sa.Column('slack_team_name', sa.String(length=255), nullable=True),
        sa.Column('slack_user_id', sa.String(length=32), nullable=True),
        sa.Column('installation_json', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('consumed', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index('ix_slack_pending_installs_id', 'slack_pending_installs', ['id'], unique=False)
    op.create_index('ix_slack_pending_installs_nonce', 'slack_pending_installs', ['nonce'], unique=True)

def downgrade():
    op.drop_index('ix_slack_pending_installs_nonce', table_name='slack_pending_installs')
    op.drop_index('ix_slack_pending_installs_id', table_name='slack_pending_installs')
    op.drop_table('slack_pending_installs')
