"""
Convert JSON columns to JSONB for performance and indexing
"""

revision = '20250839'
down_revision = '20250837'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


def _alter_json_to_jsonb(table: str, column: str, existing_nullable: bool = True):
    op.alter_column(
        table,
        column,
        existing_type=sa.JSON(),
        type_=postgresql.JSONB(astext_type=sa.Text()),
        postgresql_using=f"{column}::jsonb",
        existing_nullable=existing_nullable,
    )


def _alter_jsonb_to_json(table: str, column: str, existing_nullable: bool = True):
    op.alter_column(
        table,
        column,
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        type_=sa.JSON(),
        postgresql_using=f"{column}::json",
        existing_nullable=existing_nullable,
    )


def upgrade():
    # teams table
    _alter_json_to_jsonb('teams', 'color_scheme_data', existing_nullable=True)
    _alter_json_to_jsonb('teams', 'slack_settings', existing_nullable=True)
    _alter_json_to_jsonb('teams', 'security_settings', existing_nullable=True)

    # welcomepage_users table
    _alter_json_to_jsonb('welcomepage_users', 'handwave_emoji', existing_nullable=True)
    _alter_json_to_jsonb('welcomepage_users', 'selected_prompts', existing_nullable=False)
    _alter_json_to_jsonb('welcomepage_users', 'answers', existing_nullable=False)
    _alter_json_to_jsonb('welcomepage_users', 'page_comments', existing_nullable=True)
    _alter_json_to_jsonb('welcomepage_users', 'bento_widgets', existing_nullable=True)

    # slack_pending_installs table
    _alter_json_to_jsonb('slack_pending_installs', 'installation_json', existing_nullable=False)


def downgrade():
    # slack_pending_installs table
    _alter_jsonb_to_json('slack_pending_installs', 'installation_json', existing_nullable=False)

    # welcomepage_users table
    _alter_jsonb_to_json('welcomepage_users', 'bento_widgets', existing_nullable=True)
    _alter_jsonb_to_json('welcomepage_users', 'page_comments', existing_nullable=True)
    _alter_jsonb_to_json('welcomepage_users', 'answers', existing_nullable=False)
    _alter_jsonb_to_json('welcomepage_users', 'selected_prompts', existing_nullable=False)
    _alter_jsonb_to_json('welcomepage_users', 'handwave_emoji', existing_nullable=True)

    # teams table
    _alter_jsonb_to_json('teams', 'security_settings', existing_nullable=True)
    _alter_jsonb_to_json('teams', 'slack_settings', existing_nullable=True)
    _alter_jsonb_to_json('teams', 'color_scheme_data', existing_nullable=True)
