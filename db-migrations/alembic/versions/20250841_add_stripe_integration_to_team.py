"""
Add Stripe integration fields to teams table
"""
revision = '20250841'
down_revision = '20250839'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa

def upgrade():
    # Add Stripe integration fields
    op.add_column('teams', sa.Column('stripe_customer_id', sa.String(255), nullable=True))
    op.add_column('teams', sa.Column('stripe_subscription_id', sa.String(255), nullable=True))
    op.add_column('teams', sa.Column('subscription_status', sa.String(50), nullable=True))
    
    # Add indexes for performance
    op.create_index('ix_teams_stripe_customer_id', 'teams', ['stripe_customer_id'], unique=True)
    op.create_index('ix_teams_stripe_subscription_id', 'teams', ['stripe_subscription_id'], unique=True)

def downgrade():
    # Drop indexes
    op.drop_index('ix_teams_stripe_subscription_id', table_name='teams')
    op.drop_index('ix_teams_stripe_customer_id', table_name='teams')
    
    # Drop columns
    op.drop_column('teams', 'subscription_status')
    op.drop_column('teams', 'stripe_subscription_id')
    op.drop_column('teams', 'stripe_customer_id')
