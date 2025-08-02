"""
Add slack_settings column to welcomepage_teams
"""
revision = '20250729' #_add_slack_settings_to_team
down_revision = '20250727' #_remove_team_settings_column
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa

def upgrade():
    op.add_column('teams', sa.Column('slack_settings', sa.JSON(), nullable=True))

def downgrade():
    op.drop_column('teams', 'slack_settings')
