"""Initial migration

Revision ID: 507ccf8e06d8
Revises: 
Create Date: 2025-06-27 21:57:06.723174

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '507ccf8e06d8'
down_revision = '20250101'  # Now depends on initial schema setup
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ensure we're using the welcomepage schema (set by previous migration)
    op.execute("SET search_path TO welcomepage, public")
    
    op.create_table(
        'teams',
        sa.Column('id', sa.Integer, primary_key=True, index=True),
        sa.Column('public_id', sa.String(36), unique=True, index=True, nullable=False),
        sa.Column('organization_name', sa.String, nullable=False),
        sa.Column('company_logo_url', sa.String, nullable=True),
        sa.Column('color_scheme', sa.String, nullable=False),
        sa.Column('color_scheme_data', sa.JSON, nullable=True),
        sa.Column('is_draft', sa.Boolean, nullable=False, server_default='1'),
        schema='welcomepage',
    )

    op.create_table(
        'welcomepage_users',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('public_id', sa.String(36), unique=True, index=True, nullable=False),
        sa.Column('name', sa.String, nullable=True),
        sa.Column('role', sa.String, nullable=True),
        sa.Column('location', sa.String, nullable=True),
        sa.Column('nickname', sa.String, nullable=True),
        sa.Column('greeting', sa.String, nullable=True),
        sa.Column('handwave_emoji_url', sa.String, nullable=True),
        sa.Column('profile_photo_url', sa.String, nullable=True),
        sa.Column('wave_gif_url', sa.String, nullable=True),
        sa.Column('pronunciation_recording_url', sa.String, nullable=True),
        sa.Column('selected_prompts', sa.JSON, nullable=True),
        sa.Column('answers', sa.JSON, nullable=True),
        sa.Column('team_settings', sa.JSON, nullable=True),
        sa.Column('team_id', sa.Integer, sa.ForeignKey('teams.id'), nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now(), nullable=True),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now(), nullable=True),
        sa.Column('is_draft', sa.Boolean, nullable=True, server_default='1'),
        schema='welcomepage',
    )

def downgrade() -> None:
    op.drop_table('welcomepage_users', schema='welcomepage')
    op.drop_table('teams', schema='welcomepage')
    

