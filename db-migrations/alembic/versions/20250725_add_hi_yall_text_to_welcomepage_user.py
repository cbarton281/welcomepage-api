"""
Add hi_yall_text field to welcomepage_users
"""
revision = '20250725' #_add_hi_yall_text_to_welcomepage_user
down_revision = '20250723' #_add_auth_email_to_welcomepage_user
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa

def upgrade():
    op.add_column('welcomepage_users', sa.Column('hi_yall_text', sa.String(), nullable=True))

def downgrade():
    op.drop_column('welcomepage_users', 'hi_yall_text')
