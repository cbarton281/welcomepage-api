# Unlimited Subscription Feature

## Overview

The "unlimited" subscription tier is a special, staff-only subscription level that can be granted to teams via SQL. This is completely invisible to users and is intended for internal use cases like demos, incentives, or customer service situations.

## Purpose

- **Customer Service**: Grant unlimited access to resolve issues or compensate upset customers
- **Internal Demos**: Test scenarios without page limits or payment requirements
- **Special Offers**: Incentivize potential customers or partners
- **Bug Testing**: Test edge cases at scale without limits

## How It Works

When a team has `subscription_status = 'unlimited'`:

1. **No Page Count Checks**: Team can have any number of published pages
2. **No Payment Required**: Team doesn't need a payment method
3. **No Charges**: Publishing over the free limit won't trigger Stripe charges
4. **Full Access**: All features are available

## SQL Commands

### Grant Unlimited Access

```sql
-- Grant unlimited subscription to a team (by public_id)
UPDATE teams 
SET subscription_status = 'unlimited' 
WHERE public_id = 'team_public_id_here';

-- Or by organization name (be careful with this)
UPDATE teams 
SET subscription_status = 'unlimited' 
WHERE organization_name = 'Company Name Here';
```

### Check Current Status

```sql
-- Check if a team has unlimited access
SELECT public_id, organization_name, subscription_status 
FROM teams 
WHERE subscription_status = 'unlimited';

-- Check a specific team
SELECT public_id, organization_name, subscription_status, stripe_customer_id 
FROM teams 
WHERE public_id = 'team_public_id_here';
```

### Remove Unlimited Access

```sql
-- Revert to free (no payment method) or pro (with payment method)
-- The system will automatically determine based on stripe_customer_id

-- Option 1: Set to free if no payment method
UPDATE teams 
SET subscription_status = 'free' 
WHERE public_id = 'team_public_id_here' 
  AND stripe_customer_id IS NULL;

-- Option 2: Set to pro if has payment method
UPDATE teams 
SET subscription_status = 'pro' 
WHERE public_id = 'team_public_id_here' 
  AND stripe_customer_id IS NOT NULL;

-- Option 3: Let the system auto-determine (set to NULL)
UPDATE teams 
SET subscription_status = NULL 
WHERE public_id = 'team_public_id_here';
```

## Implementation Details

### Where It's Used

1. **`utils/team_limits.py`**: `check_team_signup_allowed()` - Bypasses signup limit checks
2. **`api/slack_publish.py`**: `publish_welcomepage_to_slack()` - Bypasses charge logic

### Code Pattern

```python
# Check for unlimited subscription first
if team.subscription_status == 'unlimited':
    log.info(f"Team {team.public_id} has unlimited subscription, bypassing checks")
    # Allow operation without any limits
    return True, "Operation allowed (unlimited subscription)"
```

## Important Notes

1. **Never expose to users**: This is staff-only. Never show this status in the UI
2. **Manual SQL only**: Can only be set/removed via direct database access
3. **Audit trail**: Consider logging when this status is changed
4. **Use sparingly**: This is an exception tool, not a regular operational procedure
5. **Document reason**: When granting unlimited, document why in internal notes

## Use Case Examples

### Customer Service

```sql
-- Customer has a bug and is frustrated
-- Grant unlimited access as compensation
UPDATE teams 
SET subscription_status = 'unlimited' 
WHERE public_id = 'customer_team_id';
-- Add note: "Bug compensation - assigned by [agent name]"
```

### Internal Demo

```sql
-- Creating demo for sales presentation
UPDATE teams 
SET subscription_status = 'unlimited' 
WHERE organization_name = 'Sales Demo Company';
```

### Testing

```sql
-- Test team for QA
UPDATE teams 
SET subscription_status = 'unlimited' 
WHERE organization_name = 'QA Test Team';
```

## Troubleshooting

### Check if a team has unlimited access

```sql
SELECT 
    public_id, 
    organization_name, 
    subscription_status,
    stripe_customer_id,
    stripe_subscription_id
FROM teams 
WHERE public_id = 'problematic_team_id';
```

### Find all unlimited teams

```sql
SELECT 
    public_id, 
    organization_name, 
    created_at,
    updated_at
FROM teams 
WHERE subscription_status = 'unlimited'
ORDER BY updated_at DESC;
```

