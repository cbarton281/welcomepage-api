from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20250831'
down_revision = '20250829'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use JSONB for PostgreSQL
    op.add_column('welcomepage_users', sa.Column('page_comments', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('welcomepage_users', 'page_comments')
