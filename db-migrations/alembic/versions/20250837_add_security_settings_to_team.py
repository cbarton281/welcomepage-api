"""
Add security_settings column to teams
"""
revision = '20250837'
down_revision = '20250835'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa

def upgrade():
    op.add_column('teams', sa.Column('security_settings', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('teams', 'security_settings')
