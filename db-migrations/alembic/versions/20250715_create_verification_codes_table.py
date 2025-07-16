"""
Alembic migration to create the verification_codes table
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20250715'
down_revision = '507ccf8e06d8'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'verification_codes',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('email', sa.String, nullable=False),
        sa.Column('code', sa.String(6), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used', sa.Boolean, nullable=False, server_default=sa.text('false')),
    )
    # Add indexes for efficient search
    op.create_index('idx_verification_codes_email', 'verification_codes', ['email'])
    op.create_index('idx_verification_codes_code', 'verification_codes', ['code'])
    op.create_index('idx_verification_codes_email_code', 'verification_codes', ['email', 'code'])

def downgrade():
    op.drop_index('idx_verification_codes_email_code', table_name='verification_codes')
    op.drop_index('idx_verification_codes_code', table_name='verification_codes')
    op.drop_index('idx_verification_codes_email', table_name='verification_codes')
    op.drop_table('verification_codes')
