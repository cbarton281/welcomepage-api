"""
Create page_visits table for visit tracking analytics

Revision ID: 20250802
Revises: 20250729
Create Date: 2025-08-02 14:01:18.000000

"""
revision = '20250802'  # create_page_visits_table
down_revision = '20250729'  # add_slack_settings_to_team
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    # Create page_visits table
    op.create_table(
        'page_visits',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('visited_user_id', sa.Integer(), nullable=False),
        sa.Column('visitor_public_id', sa.String(100), nullable=False),
        sa.Column('visit_start_time', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('visit_end_time', sa.DateTime(), nullable=True),
        sa.Column('visit_duration_seconds', sa.Integer(), nullable=True),
        sa.Column('visitor_country', sa.String(2), nullable=True),
        sa.Column('visitor_region', sa.String(100), nullable=True),
        sa.Column('visitor_city', sa.String(100), nullable=True),
        sa.Column('referrer', sa.String(512), nullable=True),
        sa.Column('user_agent', sa.String(512), nullable=True),
        sa.Column('session_id', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        schema='welcomepage',
    )
    
    # Create indexes for efficient queries
    op.create_index('idx_page_visits_visited_user_id', 'page_visits', ['visited_user_id'], schema='welcomepage')
    op.create_index('idx_page_visits_visitor_public_id', 'page_visits', ['visitor_public_id'], schema='welcomepage')
    op.create_index('idx_page_visits_visit_start_time', 'page_visits', ['visit_start_time'], schema='welcomepage')
    op.create_index('idx_page_visits_user_agent', 'page_visits', ['user_agent'], schema='welcomepage')


def downgrade():
    # Drop indexes
    op.drop_index('idx_page_visits_user_agent', 'page_visits', schema='welcomepage')
    op.drop_index('idx_page_visits_visit_start_time', 'page_visits', schema='welcomepage')
    op.drop_index('idx_page_visits_visitor_public_id', 'page_visits', schema='welcomepage')
    op.drop_index('idx_page_visits_visited_user_id', 'page_visits', schema='welcomepage')
    
    # Drop table
    op.drop_table('page_visits', schema='welcomepage')
