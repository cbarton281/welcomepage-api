"""Initial migration

Revision ID: 507ccf8e06d8
Revises: 
Create Date: 2025-06-27 21:57:06.723174

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '507ccf8e06d8'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'teams',
        sa.Column('id', sa.Integer, primary_key=True, index=True),
        sa.Column('public_id', sa.String(36), unique=True, index=True, nullable=False),
        sa.Column('organization_name', sa.String, nullable=False),
        sa.Column('company_logo_url', sa.String, nullable=True),
        sa.Column('color_scheme', sa.String, nullable=False),
        sa.Column('color_scheme_data', sa.JSON, nullable=True)
    )

    op.create_table(
        'welcomepage_users',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('name', sa.String, nullable=False),
        sa.Column('role', sa.String, nullable=False),
        sa.Column('location', sa.String, nullable=False),
        sa.Column('nickname', sa.String),
        sa.Column('greeting', sa.String, nullable=False),
        sa.Column('handwave_emoji_url', sa.String),
        sa.Column('profile_photo_url', sa.String),
        sa.Column('wave_gif_url', sa.String),
        sa.Column('pronunciation_recording_url', sa.String),
        sa.Column('selected_prompts', sa.JSON, nullable=False),
        sa.Column('answers', sa.JSON, nullable=False),
        sa.Column('team_settings', sa.JSON),
        sa.Column('team_id', sa.Integer, sa.ForeignKey('teams.id'), nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now())
    )

def downgrade() -> None:
    op.drop_table('welcomepage_users')
    op.drop_table('teams')
    

