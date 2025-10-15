# Subscription Status Refactor Proposal

## Problem
Currently, we map Stripe subscription statuses to "free" or "pro", losing valuable information about the actual subscription state.

## Proposed Solution

### Add New Column
```python
# models/team.py

# NEW: Store exact Stripe status for debugging and specific user messaging
stripe_subscription_status = Column(String(50), nullable=True)
# Values: "active", "trialing", "past_due", "canceled", "incomplete", "incomplete_expired", "unpaid"

# KEEP: Simple business logic field
subscription_status = Column(String(20), nullable=True)
# Values: "free" or "pro" only
```

### Migration
```python
# db-migrations/alembic/versions/YYYYMMDD_add_stripe_subscription_status.py

def upgrade():
    op.add_column('teams', sa.Column('stripe_subscription_status', sa.String(50), nullable=True))
    
def downgrade():
    op.drop_column('teams', 'stripe_subscription_status')
```

### Update Webhook Handlers

```python
# api/stripe_webhooks.py

async def handle_subscription_created(event: dict, db: Session):
    subscription = event["data"]["object"]
    stripe_status = subscription["status"]
    
    # Store EXACT Stripe status
    team.stripe_subscription_status = stripe_status
    
    # Map to business logic (keep existing logic)
    if stripe_status in ["active", "trialing", "past_due"]:
        team.subscription_status = "pro"
    else:
        team.subscription_status = "free"
```

## Benefits

### 1. Better User Experience
```typescript
// Frontend can show specific messages
if (stripeSubscriptionStatus === "past_due") {
    return "⚠️ Your payment failed. Please update your card to keep Pro access."
} else if (stripeSubscriptionStatus === "canceled") {
    return "Your subscription was canceled. Upgrade anytime to regain Pro features!"
} else if (subscriptionStatus === "free") {
    return "You're on the free plan. Upgrade to Pro for unlimited pages!"
}
```

### 2. Grace Periods
```python
# Can implement smart grace periods
if stripe_subscription_status == "past_due":
    if days_since_failed < 3:
        # Give them 3 days to fix payment
        effective_status = "pro"
    else:
        effective_status = "free"
```

### 3. Analytics & Monitoring
```sql
-- Track subscription health
SELECT 
    stripe_subscription_status,
    COUNT(*) as count
FROM teams
WHERE subscription_status = 'pro'
GROUP BY stripe_subscription_status;

-- Find teams at risk of churning
SELECT * FROM teams 
WHERE stripe_subscription_status IN ('past_due', 'unpaid')
ORDER BY updated_at;
```

### 4. Debugging
```
Support ticket: "My subscription is broken!"

Before: subscription_status = "free" (No idea why)
After: 
  - subscription_status = "free" (Lost access)
  - stripe_subscription_status = "past_due" (Ah! Payment failed 2 days ago)
```

### 5. Compliance & Auditing
- Full history of subscription state changes
- Know exactly when and why a subscription changed
- Better for legal/financial audits

## Implementation Plan

### Phase 1: Add Column (Non-Breaking)
- [ ] Create migration to add `stripe_subscription_status` column
- [ ] Update all webhook handlers to populate both fields
- [ ] Update billing endpoints to populate both fields
- [ ] Deploy to production (existing code keeps working)

### Phase 2: Enhance UX
- [ ] Update frontend to show specific messages based on `stripe_subscription_status`
- [ ] Implement grace period logic for `past_due` subscriptions
- [ ] Add admin dashboard to view subscription health

### Phase 3: Analytics
- [ ] Add monitoring for failed payments
- [ ] Track churn by cancellation reason
- [ ] Build retention metrics

## Backward Compatibility

✅ **Fully backward compatible** - existing code continues to use `subscription_status` ("free"/"pro")

The new `stripe_subscription_status` is additive only:
- Existing queries don't break
- Frontend access control stays the same: `subscription_status !== "pro"`
- We just gain additional context when we need it

## Alternative: Property/Method Instead of Column

If we want to keep the database simpler, we could make `subscription_status` a computed property:

```python
# models/team.py

class Team(Base):
    stripe_subscription_status = Column(String(50), nullable=True)  # Store real status
    
    @property
    def subscription_status(self):
        """Computed property: map Stripe status to free/pro"""
        if self.stripe_subscription_status in ["active", "trialing", "past_due"]:
            return "pro"
        return "free"
    
    @property
    def has_pro_access(self):
        """More explicit property for access control"""
        return self.subscription_status == "pro"
```

This keeps only ONE source of truth but provides the simple "free"/"pro" interface.

## Recommendation

**Option 1: Two Columns (Recommended for now)**
- Faster to implement
- No breaking changes
- Can migrate to computed property later

**Option 2: One Column + Computed Property**
- Cleaner data model
- Single source of truth
- Requires updating all existing queries

