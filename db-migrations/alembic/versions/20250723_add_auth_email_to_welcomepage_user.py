"""
Add auth_email field to welcomepage_users
"""
revision = '20250723' #_add_auth_email_to_welcomepage_user
down_revision = '20250722' #_add_auth_role_to_welcomepage_user
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa

def upgrade():
    op.add_column('welcomepage_users', sa.Column('auth_email', sa.String(length=256), nullable=True))

def downgrade():
    op.drop_column('welcomepage_users', 'auth_email')
