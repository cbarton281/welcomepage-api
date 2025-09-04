from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20250835'
down_revision = '20250833'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add a JSON column to store Bento Box widgets configuration
    # Kept generic (sa.JSON, nullable=True) to avoid engine-specific defaults
    op.add_column(
        'welcomepage_users',
        sa.Column('bento_widgets', sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('welcomepage_users', 'bento_widgets')
