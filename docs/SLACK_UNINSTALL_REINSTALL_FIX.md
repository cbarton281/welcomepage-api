# Slack Uninstall/Reinstall User Registration Fix

## Problem Description

When a Slack workspace uninstalls and then reinstalls the Welcomepage app, users who had previously registered were unable to re-register due to a unique constraint violation on the `slack_user_id` field.

### Steps to Reproduce the Bug

1. User is invited from a Slack workspace that has Welcomepage installed
2. User registers, creating a `welcomepage_users` record with their `slack_user_id` populated
3. Welcomepage is uninstalled from the Slack workspace
   - Installation data is cleaned up from `team.slack_settings`
   - **BUT** user records remain with `slack_user_id` still populated
4. Welcomepage is reinstalled on the same Slack workspace
5. Users are re-invited and attempt to register again
6. **FAILURE**: Registration fails with an IntegrityError due to unique constraint violation on `(team_id, slack_user_id)`

### Technical Details

The database has a unique composite index on `(team_id, slack_user_id)`:

```sql
-- From migration 20250825_make_slack_user_id_unique.py
CREATE UNIQUE INDEX idx_welcomepage_users_team_slack_user_id 
ON welcomepage_users (team_id, slack_user_id);
```

When a user tries to re-register with the same `slack_user_id`, the upsert logic in `/api/user.py` would:
1. Look up user by `id` (not provided) → not found
2. Look up user by `public_id` (new anonymous ID) → not found  
3. Try to create a new user with the existing `slack_user_id` → **IntegrityError**

## Solution: Defensive Upsert Lookup

The fix adds a third lookup step by `slack_user_id` before attempting to create a new user.

### Implementation

**File**: `/Users/charlesbarton/Documents/dev/welcomepage-api/api/user.py`  
**Function**: `upsert_user_db_logic()` (lines 694-703)

```python
# Defensive lookup: If still no user found, try looking up by slack_user_id
# This handles re-registration after Slack uninstall/reinstall where the user
# record still exists with the slack_user_id from the previous installation
if db_user is None and slack_user_id and team_id:
    db_user = db.query(WelcomepageUser).filter_by(
        slack_user_id=slack_user_id,
        team_id=team_id
    ).first()
    if db_user:
        log.info(f"Found existing user by slack_user_id: {slack_user_id} in team_id {team_id}, will update user {db_user.public_id}")
```

### How It Works

The updated upsert logic now follows this sequence:

1. **Lookup by `id`** (if provided) → returns existing user for updates
2. **Lookup by `public_id`** (if provided) → returns user for anonymous → authenticated conversion
3. **NEW: Lookup by `(slack_user_id, team_id)`** (if both provided) → returns existing user from previous Slack installation
4. **Create new user** (if no user found in steps 1-3) → only creates if truly new

When a user is found in step 3, the existing user record is updated with the new registration data instead of attempting to create a duplicate.

## Why This Approach?

### Considered Solutions

1. **Clean up on uninstall**: Clear all `slack_user_id` fields when Slack is uninstalled
   - ❌ High risk in serverless environment (Vercel)
   - ❌ Could timeout with large user counts
   - ❌ Slack webhooks expect fast responses (~3 seconds)
   - ❌ If transaction rolls back, creates inconsistent state

2. **Defensive upsert** (IMPLEMENTED): Look up by `slack_user_id` before creating
   - ✅ Fast and scoped (single user at a time)
   - ✅ Serverless-friendly (milliseconds per operation)
   - ✅ Self-healing (fixes inconsistent state automatically)
   - ✅ No batch operations or long transactions
   - ✅ Works whether or not uninstall cleanup happened

### Benefits

- **Zero-downtime fix**: Handles existing broken state gracefully
- **Future-proof**: Protects against any future uninstall/reinstall scenarios
- **Performance**: Single-row query adds negligible overhead
- **Reliability**: Works in serverless environment constraints
- **Self-documenting**: Clear log messages when conflict resolution occurs

## Testing Recommendations

1. **Manual test flow**:
   - Create a test user with a `slack_user_id` in a team
   - Attempt to register with the same `slack_user_id` via the `/users/` endpoint
   - Verify the existing user is updated instead of creating a duplicate
   - Check logs for the "Found existing user by slack_user_id" message

2. **Edge cases to verify**:
   - User with `slack_user_id` in Team A tries to register in Team B (should create new user)
   - User without `slack_user_id` registers normally (should not be affected)
   - User with different `slack_user_id` registers (should create new user)

## Related Files

- `/Users/charlesbarton/Documents/dev/welcomepage-api/api/user.py` - Implementation
- `/Users/charlesbarton/Documents/dev/welcomepage-api/db-migrations/alembic/versions/20250825_make_slack_user_id_unique.py` - Unique constraint
- `/Users/charlesbarton/Documents/dev/welcomepage-api/services/slack_event_service.py` - Uninstall event handling
- `/Users/charlesbarton/Documents/dev/welcomepage-api/models/welcomepage_user.py` - User model

## Status

✅ **FIXED** - Implemented defensive upsert lookup by `slack_user_id` (2025-10-15)

