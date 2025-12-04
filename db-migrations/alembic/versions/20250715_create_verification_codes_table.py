"""
Alembic migration to create the verification_codes table
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20250715'
down_revision = '507ccf8e06d8'  # update if needed to the correct previous migration after removing fa81ca49584f
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
        sa.Column('public_id', sa.String, nullable=True),
        schema='welcomepage',
    )
    # Add indexes for efficient search
    op.create_index('idx_verification_codes_email', 'verification_codes', ['email'], schema='welcomepage')
    op.create_index('idx_verification_codes_code', 'verification_codes', ['code'], schema='welcomepage')
    op.create_index('idx_verification_codes_email_code', 'verification_codes', ['email', 'code'], schema='welcomepage')
    op.create_index('idx_verification_codes_public_id', 'verification_codes', ['public_id'], schema='welcomepage')

def downgrade():
    op.drop_index('idx_verification_codes_email_code', table_name='verification_codes', schema='welcomepage')
    op.drop_index('idx_verification_codes_code', table_name='verification_codes', schema='welcomepage')
    op.drop_index('idx_verification_codes_email', table_name='verification_codes', schema='welcomepage')
    op.drop_index('idx_verification_codes_public_id', table_name='verification_codes', schema='welcomepage')
    op.drop_table('verification_codes', schema='welcomepage')
