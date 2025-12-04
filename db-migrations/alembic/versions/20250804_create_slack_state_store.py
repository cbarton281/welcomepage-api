"""Create slack_state_store table

Revision ID: 20250804_create_slack_state_store
Revises: 
Create Date: 2025-08-04 14:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20250804'
down_revision = '20250802'
branch_labels = None
depends_on = None


def upgrade():
    # Create slack_state_store table
    op.create_table(
        'slack_state_store',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('state', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('consumed', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='welcomepage',
    )
    
    # Create indexes for performance
    op.create_index(op.f('ix_slack_state_store_id'), 'slack_state_store', ['id'], unique=False, schema='welcomepage')
    op.create_index(op.f('ix_slack_state_store_state'), 'slack_state_store', ['state'], unique=True, schema='welcomepage')
    op.create_index(op.f('ix_slack_state_store_expires_at'), 'slack_state_store', ['expires_at'], unique=False, schema='welcomepage')


def downgrade():
    # Drop indexes
    op.drop_index(op.f('ix_slack_state_store_expires_at'), table_name='slack_state_store', schema='welcomepage')
    op.drop_index(op.f('ix_slack_state_store_state'), table_name='slack_state_store', schema='welcomepage')
    op.drop_index(op.f('ix_slack_state_store_id'), table_name='slack_state_store', schema='welcomepage')
    
    # Drop table
    op.drop_table('slack_state_store', schema='welcomepage')
