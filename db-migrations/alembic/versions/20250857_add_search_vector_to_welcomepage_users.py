"""add_search_vector_to_welcomepage_users

Revision ID: 20250857
Revises: 20250855
Create Date: 2025-01-23 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '20250857'
down_revision = '20250855'
branch_labels = None
depends_on = None


def upgrade():
    # Add search_vector column as tsvector type
    op.execute("""
        ALTER TABLE welcomepage_users 
        ADD COLUMN search_vector tsvector
    """)
    
    # Create GIN index on search_vector for fast full-text search
    op.execute("""
        CREATE INDEX idx_welcomepage_users_search_vector 
        ON welcomepage_users 
        USING GIN (search_vector)
    """)


def downgrade():
    # Remove index and column
    op.drop_index('idx_welcomepage_users_search_vector', table_name='welcomepage_users')
    op.drop_column('welcomepage_users', 'search_vector')

