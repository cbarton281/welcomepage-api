"""Make slack_user_id unique on welcomepage_users

Revision ID: 20250825
Revises: 20250815
Create Date: 2025-08-25 20:41:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20250825'
down_revision = '20250815'
branch_labels = None
depends_on = None

def upgrade():
    # Drop previous single-column index if it exists
    try:
        op.drop_index('idx_welcomepage_users_slack_user_id', table_name='welcomepage_users')
    except Exception:
        # Index may not exist on some environments; proceed
        pass

    # Create composite UNIQUE index for Enterprise Grid compatibility
    # Ensures a slack_user_id can only appear once per team, but can appear across different teams
    op.create_index(
        'idx_welcomepage_users_team_slack_user_id',
        'welcomepage_users',
        ['team_id', 'slack_user_id'],
        unique=True
    )


def downgrade():
    # Drop composite index and restore original non-unique single-column index
    try:
        op.drop_index('idx_welcomepage_users_team_slack_user_id', table_name='welcomepage_users')
    except Exception:
        pass

    op.create_index(
        'idx_welcomepage_users_slack_user_id',
        'welcomepage_users',
        ['slack_user_id'],
        unique=False
    )
