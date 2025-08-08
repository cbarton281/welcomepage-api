"""
Add intended_auth_role field to verification_codes
"""
revision = '20250807'  # _add_intended_auth_role_to_verification_codes
down_revision = '20250806'  # Latest migration
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa

def upgrade():
    op.add_column('verification_codes', sa.Column('intended_auth_role', sa.String(length=32), nullable=True, server_default='USER'))

def downgrade():
    op.drop_column('verification_codes', 'intended_auth_role')
