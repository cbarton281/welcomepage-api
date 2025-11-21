"""add_team_members_sorting_indexes

Revision ID: 20250865
Revises: 20250863
Create Date: 2025-01-23 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20250865'
down_revision = '20250863'
branch_labels = None
depends_on = None


def upgrade():
    # Create composite indexes for efficient sorting of team members
    # These indexes support filtering by team_id and sorting by the specified column
    
    # Index for sorting by date_created (Date Created column)
    op.create_index(
        'idx_welcomepage_users_team_created_at',
        'welcomepage_users',
        ['team_id', 'created_at'],
        unique=False
    )
    
    # Index for sorting by updated_at (Last Modified column)
    op.create_index(
        'idx_welcomepage_users_team_updated_at',
        'welcomepage_users',
        ['team_id', 'updated_at'],
        unique=False
    )
    
    # Index for sorting by name (Member column)
    op.create_index(
        'idx_welcomepage_users_team_name',
        'welcomepage_users',
        ['team_id', 'name'],
        unique=False
    )
    
    # Index for sorting by auth_role (Role column)
    op.create_index(
        'idx_welcomepage_users_team_auth_role',
        'welcomepage_users',
        ['team_id', 'auth_role'],
        unique=False
    )


def downgrade():
    # Drop indexes in reverse order
    op.drop_index('idx_welcomepage_users_team_auth_role', table_name='welcomepage_users')
    op.drop_index('idx_welcomepage_users_team_name', table_name='welcomepage_users')
    op.drop_index('idx_welcomepage_users_team_updated_at', table_name='welcomepage_users')
    op.drop_index('idx_welcomepage_users_team_created_at', table_name='welcomepage_users')

