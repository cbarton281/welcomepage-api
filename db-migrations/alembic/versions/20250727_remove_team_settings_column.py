"""
Remove team_settings column from welcomepage_teams
"""
revision = '20250727' #_remove_team_settings_column
down_revision = '20250725' #_add_hi_yall_text_to_welcomepage_user
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa

def upgrade():
    op.drop_column('welcomepage_users', 'team_settings')

def downgrade():
    op.add_column('welcomepage_users', sa.Column('team_settings', sa.JSON(), nullable=True))
