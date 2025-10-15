# Subscription Status Standardization

## Overview

The `subscription_status` field in the `teams` table has been **standardized to only use two values**:
- **`"pro"`** - Team has paid/active subscription
- **`"free"`** - Team is on free plan

## Changes Made

### Backend Changes

#### 1. **`models/team.py`** (Line 24)
Updated comment to reflect standardization:
```python
subscription_status = Column(String(50), nullable=True)  # Standardized: 'pro' or 'free' only
```

#### 2. **`api/stripe_billing.py`** (Line 454)
Changed hosting subscription status from "active" to "pro":
```python
team.subscription_status = "pro"  # Standardized to "pro" instead of "active"
```

#### 3. **`api/stripe_webhooks.py`** (Lines 96-106)
Added mapping logic for `subscription.created` webhook:
```python
# Map Stripe status to our standardized values: "pro" or "free"
stripe_status = subscription["status"]
if stripe_status in ["active", "trialing", "past_due"]:
    team.subscription_status = "pro"
else:
    team.subscription_status = "free"
```

#### 4. **`api/stripe_webhooks.py`** (Lines 125-133)
Added mapping logic for `subscription.updated` webhook:
```python
# Map Stripe status to our standardized values: "pro" or "free"
stripe_status = subscription["status"]
if stripe_status in ["active", "trialing", "past_due"]:
    team.subscription_status = "pro"
else:
    team.subscription_status = "free"
```

#### 5. **`api/stripe_webhooks.py`** (Line 153)
Changed deleted subscription status from "canceled" to "free":
```python
team.subscription_status = "free"  # Standardized to "free" instead of "canceled"
```

### Frontend Changes

#### 6. **`components/share-modal.tsx`** (Lines 147-156)
Simplified subscription check to only look for "pro":
```typescript
// If not on "pro" plan, show upgrade modal
// subscription_status is standardized to only "free" or "pro"
if (subscriptionStatus !== "pro") {
    console.log("[ShareModal] ADMIN with no pro subscription (status:", subscriptionStatus, ") - showing upgrade modal")
    setIsUpgradeFlow(true)
    // ... show upgrade modal
}
```

## Stripe Status Mapping

When Stripe webhooks send subscription status, we map them as follows:

### → Maps to "pro":
- `"active"` - Subscription is active and paid
- `"trialing"` - In trial period (still considered pro access)
- `"past_due"` - Payment failed but subscription still active (grace period)

### → Maps to "free":
- `"canceled"` - Subscription was canceled
- `"incomplete"` - Subscription creation incomplete
- `"incomplete_expired"` - Incomplete subscription expired
- `"unpaid"` - Subscription unpaid and delinquent
- Any other status

## All Places Where subscription_status is Set

### ✅ Correctly Sets "pro":
1. `/api/stripe_billing.py` line 514 - After payment method confirmed
2. `/api/stripe_billing.py` line 454 - When hosting subscription starts (11+ pages)
3. `/api/stripe_webhooks.py` line 101 - When Stripe subscription created (if active/trialing/past_due)
4. `/api/stripe_webhooks.py` line 128 - When Stripe subscription updated (if active/trialing/past_due)

### ✅ Correctly Sets "free":
1. `/api/stripe_billing.py` line 197 - When downgrading to free
2. `/api/stripe_webhooks.py` line 103 - When Stripe subscription created (if canceled/incomplete/etc)
3. `/api/stripe_webhooks.py` line 130 - When Stripe subscription updated (if canceled/incomplete/etc)
4. `/api/stripe_webhooks.py` line 153 - When Stripe subscription deleted
5. `/api/stripe_webhooks.py` line 165 - When Stripe customer deleted

## Benefits

1. **Simplified Logic**: Frontend only needs to check `subscriptionStatus !== "pro"`
2. **No Ambiguity**: Only two possible values instead of many Stripe statuses
3. **Consistent Behavior**: Same value whether set by billing API or Stripe webhooks
4. **Grace Period**: "past_due" is treated as "pro" to give users time to fix payment issues
5. **Future-Proof**: Easy to understand and maintain

## Migration Notes

**No database migration required** - this is a behavioral change only. Existing values will be overwritten when:
- Team upgrades/downgrades
- Stripe sends webhook events
- Hosting subscription is created/updated

Any existing teams with old values (like "active", "canceled", "trialing") will be updated to "pro" or "free" the next time their subscription changes.

## Testing Checklist

- [ ] New team upgrades → `subscription_status` becomes "pro"
- [ ] Team downgrades → `subscription_status` becomes "free"
- [ ] Stripe subscription becomes active → `subscription_status` becomes "pro"
- [ ] Stripe subscription canceled → `subscription_status` becomes "free"
- [ ] Payment fails (past_due) → `subscription_status` stays "pro" (grace period)
- [ ] ShareModal shows upgrade for status = null/free
- [ ] ShareModal skips upgrade for status = "pro"

