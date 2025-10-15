# Stripe Subscription Status Implementation

## Overview

Added a new `stripe_subscription_status` column to the `teams` table to store the **raw Stripe subscription status** while keeping the existing `subscription_status` field for simplified business logic ("free" or "pro").

## Changes Made

### 1. Database Model (`models/team.py`)

Added new column to Team model:
```python
stripe_subscription_status = Column(String(50), nullable=True)  # Raw Stripe status: 'active', 'past_due', 'canceled', etc.
subscription_status = Column(String(50), nullable=True)  # Standardized: 'pro' or 'free' only
```

### 2. Database Migration

**File:** `db-migrations/alembic/versions/20250843_add_stripe_subscription_status_to_team.py`

```python
def upgrade():
    op.add_column('teams', sa.Column('stripe_subscription_status', sa.String(50), nullable=True))

def downgrade():
    op.drop_column('teams', 'stripe_subscription_status')
```

**To run migration:**
```bash
cd db-migrations
alembic upgrade head
```

### 3. Schema Update (`schemas/team.py`)

Added field to TeamRead schema:
```python
stripe_subscription_status: Optional[str] = None  # Raw Stripe status
subscription_status: Optional[str] = None  # Simplified: "free" or "pro"
```

### 4. Stripe Webhooks (`api/stripe_webhooks.py`)

Updated all webhook handlers to populate **both** fields:

#### `handle_subscription_created` (Lines 94-110)
```python
# Store raw Stripe status for debugging and detailed messaging
stripe_status = subscription["status"]
team.stripe_subscription_status = stripe_status

# Map Stripe status to our standardized values: "pro" or "free"
if stripe_status in ["active", "trialing", "past_due"]:
    team.subscription_status = "pro"
else:
    team.subscription_status = "free"
```

#### `handle_subscription_updated` (Lines 128-140)
```python
# Store raw Stripe status
stripe_status = subscription["status"]
team.stripe_subscription_status = stripe_status

# Map to "pro" or "free"
if stripe_status in ["active", "trialing", "past_due"]:
    team.subscription_status = "pro"
else:
    team.subscription_status = "free"
```

#### `handle_subscription_deleted` (Lines 158-164)
```python
team.stripe_subscription_id = None
team.stripe_subscription_status = "canceled"  # Store raw Stripe status
team.subscription_status = "free"  # Standardized to "free"
```

#### `handle_customer_deleted` (Lines 182-189)
```python
team.stripe_customer_id = None
team.stripe_subscription_id = None
team.stripe_subscription_status = None  # Clear raw Stripe status
team.subscription_status = "free"
```

### 5. Stripe Billing API (`api/stripe_billing.py`)

Updated billing operations to populate both fields:

#### Downgrade to Free (Line 197)
```python
team.stripe_subscription_status = None  # Clear raw Stripe status
team.subscription_status = "free"
```

#### Hosting Subscription Created (Line 455)
```python
team.stripe_subscription_status = "active"  # Store raw Stripe status
team.subscription_status = "pro"  # Standardized to "pro"
```

#### Payment Method Confirmed (Line 517)
```python
# Note: This is a setup for per-page charges, not a subscription yet
team.stripe_subscription_status = None  # No subscription yet, just payment method
team.subscription_status = "pro"  # But they have pro access for per-page billing
```

## Field Values

### `stripe_subscription_status` (Raw Stripe Values)

| Value | Meaning |
|-------|---------|
| `"active"` | Subscription is active and paid |
| `"trialing"` | In trial period |
| `"past_due"` | Payment failed, in retry period |
| `"canceled"` | Subscription was canceled |
| `"incomplete"` | Subscription creation incomplete |
| `"incomplete_expired"` | Incomplete subscription expired |
| `"unpaid"` | Subscription unpaid and delinquent |
| `null` | No subscription (using per-page billing or free plan) |

### `subscription_status` (Business Logic Values)

| Value | Meaning | Access Level |
|-------|---------|--------------|
| `"pro"` | Team has paid access | Can publish unlimited |
| `"free"` | Team is on free plan | Must upgrade to publish |
| `null` | Not set yet (new teams) | Treated as "free" |

## Mapping Logic

```python
# Stripe Status → subscription_status mapping
if stripe_status in ["active", "trialing", "past_due"]:
    subscription_status = "pro"
else:
    subscription_status = "free"
```

**Note:** `"past_due"` is mapped to `"pro"` to give users a grace period (~30 days) to fix payment issues before losing access.

## Use Cases

### 1. Access Control (Simple)
```python
# Frontend or backend checks
if team.subscription_status == "pro":
    allow_publish()
else:
    show_upgrade_modal()
```

### 2. Detailed User Messaging (Enhanced)
```python
# Show specific messages based on raw Stripe status
if team.stripe_subscription_status == "past_due":
    show_message("⚠️ Your payment failed. Please update your card to keep Pro access.")
elif team.stripe_subscription_status == "canceled":
    show_message("Your subscription was canceled. Upgrade to regain Pro features.")
elif team.stripe_subscription_status == "trialing":
    show_message("🎉 You're in your free trial! Enjoy all Pro features.")
elif team.subscription_status == "free":
    show_message("You're on the free plan. Upgrade to Pro for unlimited pages!")
```

### 3. Analytics & Monitoring
```sql
-- Find teams at risk of churning
SELECT 
    public_id,
    organization_name,
    stripe_subscription_status,
    subscription_status,
    updated_at
FROM teams
WHERE stripe_subscription_status = 'past_due'
ORDER BY updated_at;

-- Subscription health report
SELECT 
    stripe_subscription_status,
    COUNT(*) as count
FROM teams
WHERE subscription_status = 'pro'
GROUP BY stripe_subscription_status;
```

### 4. Debugging Support Issues
```
User: "My subscription is broken! I can't publish."

Support checks database:
- subscription_status: "free" (Lost access)
- stripe_subscription_status: "past_due" (Payment failed 5 days ago)

Support response: "Your payment failed on [date]. Please update your card at [link]."
```

## Backward Compatibility

✅ **Fully backward compatible** - No breaking changes:

- Existing code continues to use `subscription_status` ("free"/"pro")
- Frontend access control unchanged: `subscription_status !== "pro"`
- The new `stripe_subscription_status` is additive only
- All existing queries continue to work

## Testing Checklist

After deploying:

- [ ] Run migration: `alembic upgrade head`
- [ ] Verify column exists: `SELECT stripe_subscription_status FROM teams LIMIT 1;`
- [ ] Create new subscription → Check both fields populated
- [ ] Simulate payment failure → Verify `stripe_subscription_status = "past_due"` and `subscription_status = "pro"`
- [ ] Cancel subscription → Verify `stripe_subscription_status = "canceled"` and `subscription_status = "free"`
- [ ] Check API response includes `stripe_subscription_status`

## Next Steps (Future Enhancements)

1. **Enhanced User Messaging**
   - Update frontend to show specific messages based on `stripe_subscription_status`
   - Add warning banners for `past_due` subscriptions

2. **Grace Period Logic**
   - Implement smarter grace periods (e.g., 7 days instead of 30 days)
   - Send email alerts when payment fails

3. **Analytics Dashboard**
   - Build admin dashboard showing subscription health
   - Track churn metrics and failed payments
   - Monitor trial conversions

4. **Automated Alerts**
   - Email users when payment fails
   - Slack/Discord notifications for support team
   - Automated retry reminders

## Files Changed

1. ✅ `models/team.py` - Added `stripe_subscription_status` column
2. ✅ `schemas/team.py` - Added field to TeamRead schema
3. ✅ `db-migrations/alembic/versions/20250843_add_stripe_subscription_status_to_team.py` - Migration file
4. ✅ `api/stripe_webhooks.py` - Updated all webhook handlers
5. ✅ `api/stripe_billing.py` - Updated billing operations

## Summary

This change gives you **the best of both worlds**:

- ✅ **Simple access control** via `subscription_status` ("free"/"pro")
- ✅ **Rich debugging information** via `stripe_subscription_status` (raw Stripe values)
- ✅ **No breaking changes** - existing code continues to work
- ✅ **Future-proof** - enables better UX and analytics down the road

The system now tracks the full subscription lifecycle while maintaining simple business logic for access control.

