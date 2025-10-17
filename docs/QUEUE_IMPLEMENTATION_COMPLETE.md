# Queue Implementation - Complete

## Overview

Fully implemented payment queue system for pages published over the 3-page free limit. When users publish pages without a team payment method, the pages are queued and automatically processed when payment is added.

## Implementation Summary

### **The Flow:**

#### **Scenario 1: Team with Payment Method (Synchronous)**
```
1. USER publishes 4th page
2. System checks: published_count >= 3? ✅
3. System checks: team has payment method? ✅
4. Charge $7.99 immediately
5. Publish to Slack
6. Done ✅
```

#### **Scenario 2: Team without Payment Method (Queue)**
```
1. USER publishes 4th page
2. System checks: published_count >= 3? ✅
3. System checks: team has payment method? ❌
4. Queue the page (set publish_queued=True)
5. Return: "Page queued - waiting for team admin to add payment method"
6. Vercel cron runs every 5 minutes
7. Worker checks queued pages
8. Team still has no payment? → Skip
9. Team now has payment? → Charge + Publish + Unqueue
```

---

## Files Created/Modified

### **1. Database Model** ✅
**File:** `models/welcomepage_user.py`

Added fields:
```python
publish_queued = Column(Boolean, nullable=False, default=False, server_default='0')
queued_at = Column(DateTime, nullable=True)
```

### **2. Migration** ✅
**File:** `db-migrations/alembic/versions/20250849_add_publish_queue_fields.py`

- Adds `publish_queued` and `queued_at` columns
- Creates composite index on `(publish_queued, team_id)` for efficient worker queries

**To run:**
```bash
cd db-migrations
alembic upgrade head
```

### **3. Schema** ✅
**File:** `schemas/welcomepage_user.py`

Added fields to DTO:
```python
publish_queued: Optional[bool] = Field(None, alias="publishQueued")
queued_at: Optional[str] = Field(None, alias="queuedAt")
```

### **4. Queue Logic in Publish Flow** ✅
**File:** `api/slack_publish.py` (lines 43-111)

When user publishes:
1. Count published pages for team
2. If >= 3 and no payment method → Queue it
3. If >= 3 and has payment method → Charge $7.99 then publish
4. If < 3 → Publish immediately (free limit)

### **5. Worker Processing Logic** ✅
**File:** `api/worker_queued_pages.py`

Implements complete queue processing:
- Find all queued pages
- Group by team
- Check if team has payment method
- Charge and publish queued pages
- Track success/failure counts

### **6. Queue Status Endpoint** ✅
**File:** `api/queue_status.py`

New endpoint: `GET /api/queue/status/{team_public_id}`

Returns:
- Published page count
- Queued page count
- Details of each queued page (user, date, days queued)
- Whether team has payment method

### **7. Next.js Worker Route** ✅
**File:** `app/api/worker/process-queued-pages/route.ts`

- Secured with CRON_SECRET
- Configured with 300-second timeout
- Proxies to FastAPI worker

### **8. Vercel Cron Configuration** ✅
**File:** `vercel.json`

```json
{
  "crons": [{
    "path": "/api/worker/process-queued-pages",
    "schedule": "*/5 * * * *"
  }],
  "functions": {
    "app/api/worker/process-queued-pages/route.ts": {
      "maxDuration": 300
    }
  }
}
```

### **9. FastAPI Router Registration** ✅
**File:** `app.py`

Registered new routers:
- `worker_router` - Worker endpoint
- `queue_status_router` - Queue status endpoint

---

## Database Schema

### **New Fields on `welcomepage_users`:**

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `publish_queued` | `BOOLEAN` | `FALSE` | True if page is queued for payment |
| `queued_at` | `DATETIME` | `NULL` | When the page was queued |

### **New Index:**
```sql
CREATE INDEX idx_welcomepage_users_publish_queued 
ON welcomepage_users (publish_queued, team_id);
```

**Purpose:** Efficient worker queries to find queued pages by team

---

## API Endpoints

### **1. Publish Welcomepage** (Modified)
```
POST /api/slack/publish-welcomepage
```

**New behavior:**
- Counts published pages
- If >= 3 pages:
  - Has payment → Charge $7.99 → Publish
  - No payment → Queue page → Return queued status
- If < 3 pages → Publish immediately (free)

**Responses:**
```json
// Queued
{
  "success": true,
  "message": "Page queued - waiting for team admin to add payment method",
  "slack_response": {"queued": true, "reason": "payment_required"}
}

// Charged and published
{
  "success": true,
  "message": "Published successfully",
  "slack_response": { ... }
}

// Payment failed
{
  "error": "Payment failed",
  "message": "Payment failed. Please update your payment method in team settings."
}
```

### **2. Queue Status** (New)
```
GET /api/queue/status/{team_public_id}
```

**Auth:** ADMIN only

**Response:**
```json
{
  "team_public_id": "abc123",
  "team_name": "Acme Corp",
  "published_count": 5,
  "queued_count": 2,
  "queued_pages": [
    {
      "user_public_id": "user1",
      "user_name": "John Doe",
      "queued_at": "2025-10-16T12:00:00Z",
      "days_queued": 2
    }
  ],
  "has_payment_method": false
}
```

### **3. Worker Endpoint** (New)
```
POST /api/worker/process-queued-pages
```

**Auth:** CRON_SECRET via `X-Worker-Secret` header

**Response:**
```json
{
  "success": true,
  "processed_count": 5,
  "failed_count": 1,
  "skipped_count": 3,
  "duration_ms": 4523,
  "timestamp": "2025-10-16T12:05:00Z"
}
```

---

## Configuration

### **Environment Variables:**

Add to both Next.js and FastAPI `.env`:
```bash
# Generate a secure secret
CRON_SECRET=your-random-secret-here

# Example generation:
# openssl rand -base64 32
```

Add to Vercel project settings:
- Go to project → Settings → Environment Variables
- Add `CRON_SECRET` for both deployments (Next.js and FastAPI)

---

## Testing

### **1. Test Queue Creation**

```python
# Manually queue a page for testing
from models.welcomepage_user import WelcomepageUser
from datetime import datetime, timezone

user = db.query(WelcomepageUser).filter_by(public_id='test_user').first()
user.publish_queued = True
user.queued_at = datetime.now(timezone.utc)
db.commit()
```

### **2. Test Queue Status Endpoint**

```bash
# Get queue status for your team
curl http://localhost:8000/api/queue/status/your_team_id \
  -H "Authorization: Bearer YOUR_JWT"
```

### **3. Test Worker Manually**

```bash
# Call worker endpoint directly (without waiting for cron)
curl -X POST http://localhost:3000/api/worker/process-queued-pages \
  -H "Authorization: Bearer YOUR_CRON_SECRET"
```

### **4. Test Full Flow**

**Setup:**
1. Create team without payment method
2. Have team publish 4+ pages as different users
3. Pages should queue automatically

**Verify:**
```bash
# Check queue
curl /api/queue/status/{team_id}
# Should show queued_count > 0
```

**Add payment:**
1. Admin adds payment method via team settings
2. Wait for cron (max 5 minutes) OR call worker manually
3. Check queue again → queued_count should be 0
4. Check Slack → Pages should be published

---

## User Experience

### **For Regular Users (USER role):**

**Publishing 1st-3rd page:**
```
✅ Publishes immediately (free)
No payment required
```

**Publishing 4th+ page:**

**If team has payment:**
```
🔄 Processing payment...
✅ Published! ($7.99 charged to team)
```

**If team has NO payment:**
```
⏳ Page queued
"Your page is waiting for payment. Ask your team admin to add a payment method."
```

### **For Admins (ADMIN role):**

**First publish (no payment yet):**
```
Shows UpgradeModal
→ Can add payment
→ OR skip and publish on free plan
```

**Publishing 4th+ page without payment:**
```
⏳ Page queued
"Add payment method in team settings to publish queued pages"
```

**After adding payment:**
```
🔄 Worker runs (within 5 minutes)
✅ All queued pages automatically charged and published
```

**Viewing queue:**
```
GET /api/queue/status/{team_id}

Shows:
- 2 pages queued
- Alice's page (queued 3 days ago)
- Bob's page (queued 1 day ago)
- "Add payment method to publish these pages"
```

---

## Worker Details

### **Execution Schedule:**
- Runs every 5 minutes: `*/5 * * * *`
- Max duration: 300 seconds (5 minutes)
- Vercel Pro required for custom cron schedules

### **Processing Logic:**
1. Find all users with `publish_queued = True`
2. Group by `team_id` for efficiency
3. For each team:
   - Skip if no `stripe_customer_id`
   - Charge $7.99 per queued page
   - Publish successful charges to Slack
   - Mark as `is_draft = False`, `publish_queued = False`
4. Return counts: processed, failed, skipped

### **Error Handling:**
- Payment fails → Increment `failed_count`, leave queued
- Publish fails → Increment `failed_count`, leave queued
- Team not found → Increment `skipped_count`
- No payment method → Increment `skipped_count`

### **Monitoring:**
- All processing logged to FastAPI logs
- View in Vercel → Functions → process-queued-pages
- Check execution count, duration, errors

---

## Future Enhancements

### **1. Admin Notifications**

Add email/Slack alerts:
```python
# When page is queued
send_admin_notification(
    team_id=team.id,
    message=f"{user.name} has a page queued. Add payment to publish."
)

# When queued pages are published
send_user_notification(
    user_id=user.id,
    message="Your queued page has been published!"
)
```

### **2. UI Indicators**

Show queue status in team settings:
```typescript
{queuedCount > 0 && (
  <Alert>
    You have {queuedCount} pages waiting for payment.
    Add a payment method to publish them.
  </Alert>
)}
```

### **3. Manual Queue Processing**

Add button for ADMIN to manually trigger:
```typescript
<Button onClick={processQueueNow}>
  Process Queued Pages Now
</Button>
```

### **4. Queue Expiration**

Auto-cancel pages queued > 30 days:
```python
# In worker
old_queued = db.query(WelcomepageUser).filter(
    WelcomepageUser.publish_queued == True,
    WelcomepageUser.queued_at < thirty_days_ago
).all()

for user in old_queued:
    user.publish_queued = False
    user.queued_at = None
    # Optionally notify user
```

### **5. Retry Logic**

Track failed charge attempts:
```python
# Add field: charge_attempts = Column(Integer)
# After 3 failed attempts, notify admin
```

---

## Testing Checklist

- [ ] Run migration: `alembic upgrade head`
- [ ] Deploy to Vercel with CRON_SECRET set
- [ ] Test: Publish 1-3 pages → Should publish immediately
- [ ] Test: Publish 4th page without payment → Should queue
- [ ] Test: Check `/api/queue/status` → Should show queued page
- [ ] Test: Add payment method → Wait 5 min → Page auto-published
- [ ] Test: Manual worker call → Should process queue
- [ ] Verify cron runs every 5 minutes in Vercel logs
- [ ] Verify charges appear in Stripe dashboard
- [ ] Test: Payment failure → Page stays queued

---

## Summary

✅ **Database:** Added `publish_queued` and `queued_at` fields
✅ **Migration:** Created and ready to run
✅ **Publish Flow:** Checks page count, queues if needed
✅ **Worker:** Processes queue every 5 minutes
✅ **Queue Status:** API to view queued pages
✅ **Charging:** Integrated with Stripe billing
✅ **Security:** Protected with CRON_SECRET
✅ **Monitoring:** Comprehensive logging

## Deployment Steps

1. **Set CRON_SECRET:**
   ```bash
   # Vercel dashboard → Environment Variables
   CRON_SECRET=<generate-secure-secret>
   ```

2. **Run Migration:**
   ```bash
   cd welcomepage-api/db-migrations
   alembic upgrade head
   ```

3. **Deploy to Vercel:**
   ```bash
   git add .
   git commit -m "Implement payment queue system"
   git push
   ```

4. **Verify Cron:**
   - Vercel dashboard → Project → Crons
   - Should show: `process-queued-pages` running every 5 minutes

5. **Test:**
   - Publish pages over limit without payment
   - Verify they queue
   - Add payment method
   - Wait 5 minutes
   - Verify pages auto-publish

The queue system is now fully implemented and ready for deployment! 🎉

