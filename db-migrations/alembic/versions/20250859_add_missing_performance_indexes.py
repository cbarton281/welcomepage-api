"""add_missing_performance_indexes

Revision ID: 20250859
Revises: 20250857
Create Date: 2025-11-04 10:26:47.555824

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20250859'
down_revision = '20250857'
branch_labels = None
depends_on = None


def upgrade():
    # Create indexes for welcomepage_users table
    op.create_index('idx_welcomepage_users_team_id', 'welcomepage_users', ['team_id'], unique=False)
    op.create_index('idx_welcomepage_users_team_draft', 'welcomepage_users', ['team_id', 'is_draft'], unique=False)
    op.create_index('idx_page_visits_user_visitor', 'page_visits', ['visited_user_id', 'visitor_public_id'], unique=False)
    # Partial index with WHERE clause
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_verification_codes_email_used
        ON verification_codes (email, used)
        WHERE used = false
    """)



def downgrade():
    # Drop indexes in reverse order
    op.execute("DROP INDEX IF EXISTS idx_verification_codes_email_used")
    op.drop_index('idx_page_visits_user_visitor', table_name='page_visits')
    op.drop_index('idx_welcomepage_users_team_draft', table_name='welcomepage_users')
    op.drop_index('idx_welcomepage_users_team_id', table_name='welcomepage_users')
