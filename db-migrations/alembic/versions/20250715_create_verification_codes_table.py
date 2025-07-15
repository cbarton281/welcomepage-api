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
        sa.Column('email', sa.String, index=True, nullable=False),
        sa.Column('code', sa.String(6), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used', sa.Boolean, nullable=False, server_default=sa.text('false')),
    )

def downgrade():
    op.drop_table('verification_codes')
