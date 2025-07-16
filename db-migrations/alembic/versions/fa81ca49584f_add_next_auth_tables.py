"""add next-auth tables

Revision ID: fa81ca49584f
Revises: 20250715
Create Date: 2025-07-15 20:33:49.954370

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'fa81ca49584f'
down_revision: Union[str, None] = '20250715'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade():
    op.create_table(
        'User',
        sa.Column('id', sa.String(length=25), primary_key=True),
        sa.Column('email', sa.String, unique=True, nullable=True),
        sa.Column('emailVerified', sa.DateTime(timezone=True), nullable=True),
        sa.Column('public_id', sa.String, unique=True, nullable=True),
        sa.Column('role', sa.String, nullable=True),
    )
    op.create_table(
        'Session',
        sa.Column('id', sa.String(length=25), primary_key=True),
        sa.Column('sessionToken', sa.String, unique=True, nullable=False),
        sa.Column('userId', sa.String(length=25), sa.ForeignKey('User.id'), nullable=False),
        sa.Column('expires', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        'VerificationToken',
        sa.Column('identifier', sa.String, nullable=False),
        sa.Column('token', sa.String, unique=True, nullable=False),
        sa.Column('expires', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('identifier', 'token')
    )

def downgrade():
    op.drop_table('VerificationToken')
    op.drop_table('Session')
    op.drop_table('User')