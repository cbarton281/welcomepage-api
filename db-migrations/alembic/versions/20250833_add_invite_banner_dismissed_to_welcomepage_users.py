from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20250833'
down_revision = '20250831'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('welcomepage_users', sa.Column('invite_banner_dismissed', sa.Boolean(), nullable=True, server_default=sa.text('false')))


def downgrade() -> None:
    op.drop_column('welcomepage_users', 'invite_banner_dismissed')
