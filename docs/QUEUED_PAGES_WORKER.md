# Queued Pages Worker Setup

## Overview

The queued pages worker processes welcomepage publications that are waiting for payment. This is needed when non-ADMIN users (USER or PRE_SIGNUP) want to publish pages but the team doesn't have a payment method registered yet.

## Architecture

### **Flow:**

1. **USER publishes 4th page** (over 3-page free limit)
2. **Check:** Team has payment method?
   - ✅ Yes → Charge $7.99 immediately → Publish
   - ❌ No → **Queue the page** (set `publish_queued = True`)
3. **Vercel cron** runs every 5 minutes → Calls worker
4. **Worker processes** queued pages:
   - Find teams with queued pages
   - Check if they now have payment method
   - Charge $7.99 per queued page
   - Publish successfully charged pages

### **Components:**

```
Next.js Worker Route
  ↓ (calls every 5 min via Vercel cron)
FastAPI Worker Endpoint
  ↓ (processes)
Database: welcomepage_users with publish_queued flag
```

## Files Created

### 1. **Next.js Worker Route**
**File:** `/app/api/worker/process-queued-pages/route.ts`

- Protected by `CRON_SECRET` environment variable
- Configured with `maxDuration: 300` seconds (5 minutes)
- Proxies to FastAPI worker endpoint
- Logs execution time and results

### 2. **FastAPI Worker Endpoint**
**File:** `/api/worker_queued_pages.py`

- Endpoint: `POST /api/worker/process-queued-pages`
- Protected by `X-Worker-Secret` header
- Shell implementation ready for queue processing logic

### 3. **Vercel Configuration**
**File:** `/vercel.json`

```json
{
  "crons": [
    {
      "path": "/api/worker/process-queued-pages",
      "schedule": "*/5 * * * *"
    }
  ],
  "functions": {
    "app/api/worker/process-queued-pages/route.ts": {
      "maxDuration": 300
    }
  }
}
```

### 4. **FastAPI Router Registration**
**File:** `/app.py`

Added worker router to FastAPI app:
```python
from api.worker_queued_pages import router as worker_router
app.include_router(worker_router, prefix="/api")
```

## Environment Variables Required

### **Both Next.js and FastAPI need:**

```bash
# Shared secret for worker authentication
CRON_SECRET=your-random-secret-key-here
```

**Generate a secure secret:**
```bash
# Option 1: OpenSSL
openssl rand -base64 32

# Option 2: Python
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Option 3: Node
node -e "console.log(require('crypto').randomBytes(32).toString('base64'))"
```

**Add to:**
- Vercel environment variables (Next.js)
- Vercel environment variables (FastAPI)
- Local `.env` file for development

## Vercel Cron Schedule

### **Current Configuration:**
```
schedule: "*/5 * * * *"
```

**Means:** Every 5 minutes

### **Cron Syntax:**
```
┌───────────── minute (0 - 59)
│ ┌───────────── hour (0 - 23)
│ │ ┌───────────── day of month (1 - 31)
│ │ │ ┌───────────── month (1 - 12)
│ │ │ │ ┌───────────── day of week (0 - 6, Sunday = 0)
│ │ │ │ │
* * * * *
```

### **Examples:**
- `*/5 * * * *` - Every 5 minutes
- `*/10 * * * *` - Every 10 minutes
- `0 * * * *` - Every hour at minute 0
- `0 0 * * *` - Daily at midnight
- `0 */6 * * *` - Every 6 hours

## Security

### **Authentication Flow:**

1. **Vercel cron** calls Next.js route with header:
   ```
   Authorization: Bearer ${CRON_SECRET}
   ```

2. **Next.js route** verifies secret:
   ```typescript
   if (authHeader !== `Bearer ${cronSecret}`) {
     return 401 Unauthorized
   }
   ```

3. **Next.js** calls FastAPI with header:
   ```
   X-Worker-Secret: ${CRON_SECRET}
   ```

4. **FastAPI** verifies secret:
   ```python
   if worker_secret != expected_secret:
     raise HTTPException(401)
   ```

### **Why Two Layers?**

- Next.js layer: Vercel automatically adds `Authorization` header to cron requests
- FastAPI layer: Additional verification that request came from our Next.js (not external)

## Function Timeout Configuration

### **maxDuration: 300 seconds (5 minutes)**

**Why 300 seconds?**
- Default Vercel function timeout: 10 seconds (too short for processing multiple pages)
- Pro plan allows: up to 300 seconds (5 minutes)
- Worker might need to:
  - Query database for queued pages
  - Charge multiple Stripe payments (each ~2 seconds)
  - Publish multiple Slack messages (each ~1 second)
  - With 100 queued pages: ~300 seconds total

**Configured in vercel.json:**
```json
"functions": {
  "app/api/worker/process-queued-pages/route.ts": {
    "maxDuration": 300
  }
}
```

## Database Schema (To Be Added)

### **Option 1: Add fields to welcomepage_users**
```python
# models/welcomepage_user.py
publish_queued = Column(Boolean, default=False)  # Page is queued for payment
queued_at = Column(DateTime, nullable=True)      # When it was queued
```

### **Option 2: Separate queue table** (if you need more tracking)
```python
class PublishQueue(Base):
    __tablename__ = 'publish_queue'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('welcomepage_users.id'))
    team_id = Column(Integer, ForeignKey('teams.id'))
    queued_at = Column(DateTime)
    status = Column(String)  # 'pending', 'processing', 'completed', 'failed'
    charge_amount = Column(Integer)  # 799 cents
    attempts = Column(Integer, default=0)
    last_attempt = Column(DateTime, nullable=True)
    error_message = Column(String, nullable=True)
```

**Recommendation:** Start with Option 1 (simpler)

## Worker Implementation (TODO)

The worker shell is ready. Next steps to implement:

### **1. Add Database Fields**
- Migration to add `publish_queued` and `queued_at` columns

### **2. Implement Queue Logic in Publish Flow**
```python
# In slack_publish.py or user.py
if published_count >= 3:
    if team.stripe_customer_id:
        # Charge immediately
        charge_for_welcomepage(team_id, user_id)
        publish_to_slack(user_id)
    else:
        # Queue it
        user.publish_queued = True
        user.queued_at = datetime.now(timezone.utc)
        db.commit()
        return {"status": "queued", "message": "Page queued until payment added"}
```

### **3. Implement Worker Processing Logic**
```python
# In worker_queued_pages.py
def process_queued_pages(db: Session):
    # Find queued pages
    queued_users = db.query(WelcomepageUser).filter(
        WelcomepageUser.publish_queued == True
    ).all()
    
    # Group by team
    teams_with_queued = {}
    for user in queued_users:
        if user.team_id not in teams_with_queued:
            teams_with_queued[user.team_id] = []
        teams_with_queued[user.team_id].append(user)
    
    # Process each team
    for team_id, users in teams_with_queued.items():
        team = db.query(Team).get(team_id)
        
        # Skip if no payment method
        if not team.stripe_customer_id:
            continue
        
        # Charge and publish each queued page
        for user in users:
            try:
                charge_for_welcomepage(team_id, user.public_id)
                publish_to_slack(user.public_id)
                user.publish_queued = False
                user.is_draft = False
                db.commit()
            except Exception as e:
                log.error(f"Failed to process queued page for {user.public_id}: {e}")
```

### **4. Add Admin Notifications**
- Email admin when pages are queued
- Show count in team settings: "You have 3 queued pages"
- Notify when queued pages are published

## Testing

### **Local Testing (Without Cron):**

Call the worker manually:
```bash
# Get your CRON_SECRET from .env
curl -X GET http://localhost:3000/api/worker/process-queued-pages \
  -H "Authorization: Bearer YOUR_CRON_SECRET"
```

### **Vercel Testing:**

Vercel provides a way to manually trigger cron:
1. Go to Vercel Dashboard → Project → Crons
2. Click "Run" next to your cron job
3. Check function logs

### **Database Testing:**

```sql
-- Create a queued page for testing
UPDATE welcomepage_users
SET publish_queued = true, queued_at = NOW()
WHERE public_id = 'test_user_id';

-- Check after worker runs
SELECT public_id, publish_queued, is_draft
FROM welcomepage_users
WHERE publish_queued = true;
```

## Monitoring

### **Check Worker Execution:**

**Vercel Dashboard:**
- Functions → Filter by `process-queued-pages`
- View execution logs
- Check success/failure rate

**Add Monitoring:**
```python
# In worker
log.info(f"Processed {processed_count} pages successfully")
log.error(f"Failed to process {failed_count} pages")

# Optional: Send to monitoring service
# send_to_datadog/sentry/etc.
```

## Cost Considerations

### **Vercel Cron:**
- Included in Pro plan ($20/month)
- Counts toward function invocations
- Every 5 minutes = ~8,640 invocations/month

### **Function Duration:**
- Each execution can take up to 300 seconds
- Charges based on GB-seconds used
- Monitor actual usage in Vercel dashboard

### **Optimization:**
- If no queued pages → Exit early (milliseconds)
- Only process in batches if many queued
- Add early termination if approaching timeout

## Alternative: Manual Processing

Instead of cron, process queue when:

1. **Admin adds payment method** → Auto-process queue immediately
2. **Admin visits team settings** → Show "Process Queue" button
3. **Stripe webhook** (payment_method.attached) → Auto-process queue

This eliminates cron entirely! Worth considering if you want to reduce complexity.

## Next Steps

1. ✅ Worker shell created
2. ✅ Vercel cron configured
3. ✅ Security setup documented
4. ⏳ Add database fields for queue
5. ⏳ Implement queue logic in publish flow
6. ⏳ Implement worker processing logic
7. ⏳ Add admin notifications
8. ⏳ Deploy and test with CRON_SECRET

## Files Summary

- ✅ `welcomepage-new-prompts/app/api/worker/process-queued-pages/route.ts` - Next.js worker route
- ✅ `welcomepage-new-prompts/vercel.json` - Cron configuration
- ✅ `welcomepage-api/api/worker_queued_pages.py` - FastAPI worker endpoint (shell)
- ✅ `welcomepage-api/app.py` - Router registered
- 📝 `welcomepage-api/docs/QUEUED_PAGES_WORKER.md` - This documentation

