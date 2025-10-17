# Batch Worker Architecture

## Overview

The queue worker has been refactored into a modular batch processing system that can handle multiple types of scheduled background tasks. The architecture is designed to be extensible for future batch operations.

## Design Philosophy

**Single Worker, Multiple Processes**

Instead of creating separate cron jobs for each batch process, we use one worker endpoint that orchestrates multiple batch operations. This approach:
- ✅ Reduces Vercel cron job count (limited resource)
- ✅ Shares infrastructure and monitoring
- ✅ Centralizes security and logging
- ✅ Makes adding new processes simple

## Architecture

### **File Structure:**

```
welcomepage-api/api/queue_worker.py
├── process_queued_pages()      # Batch process: Queue processing
├── send_dunning_emails()        # Batch process: Dunning emails (future)
└── queue_worker()               # Main endpoint: Orchestrates all processes
```

### **Flow:**

```
Vercel Cron (every 5 min)
    ↓
Next.js: /api/worker/process-queued-pages
    ↓ (validates CRON_SECRET)
FastAPI: /api/worker/queue_worker
    ↓ (validates X-Worker-Secret)
Executes batch processes:
    ├─ process_queued_pages()
    ├─ send_dunning_emails() (future)
    └─ cleanup_expired_data() (future)
    ↓
Returns aggregated results
```

## Current Batch Processes

### **1. Process Queued Pages** ✅ Implemented

**Function:** `process_queued_pages(db: Session)`

**Purpose:** Charge and publish pages that were queued due to missing payment method

**Logic:**
1. Find all users with `publish_queued = True`
2. Group by `team_id` for efficiency
3. For each team:
   - Skip if no `stripe_customer_id`
   - Charge $7.99 per queued page
   - Publish successful charges to Slack
   - Mark as published (`is_draft = False`, `publish_queued = False`)
4. Return counts: processed, failed, skipped

**Returns:**
```python
{
    "processed_count": 5,
    "failed_count": 1,
    "skipped_count": 3
}
```

### **2. Send Dunning Emails** 📋 Future

**Function:** `send_dunning_emails(db: Session)` (stub created)

**Purpose:** Remind admins to update payment methods for failed subscriptions

**Planned Logic:**
1. Find teams with `stripe_subscription_status = 'past_due'`
2. Check when last dunning email was sent (need to track)
3. Send email to team admins with update payment link
4. Track email send success/failure

**Returns:**
```python
{
    "emails_sent": 10,
    "failed_count": 2
}
```

**TODO:**
- Add `last_dunning_email_sent` field to teams table
- Implement email sending logic
- Add dunning email template
- Uncomment in main worker (line 211)

### **3. Other Future Processes** 📋

Easy to add:

```python
async def cleanup_expired_data(db: Session) -> Dict[str, Any]:
    """Remove verification codes older than 30 days"""
    # Implementation here
    return {"cleaned_count": X}

async def aggregate_analytics(db: Session) -> Dict[str, Any]:
    """Pre-compute daily analytics"""
    # Implementation here
    return {"aggregated_teams": X}

async def send_engagement_emails(db: Session) -> Dict[str, Any]:
    """Send weekly digest emails"""
    # Implementation here
    return {"emails_sent": X}
```

Then add to main worker:
```python
cleanup_result = await cleanup_expired_data(db)
results["cleanup"] = cleanup_result
```

## Main Worker Endpoint

### **Route:**
```
POST /api/worker/queue_worker
```

### **Security:**
- Protected by `X-Worker-Secret` header
- Must match `CRON_SECRET` environment variable
- Returns 401 if unauthorized

### **Response:**
```json
{
  "success": true,
  "results": {
    "queued_pages": {
      "processed_count": 5,
      "failed_count": 1,
      "skipped_count": 3
    },
    "dunning_emails": {
      "emails_sent": 10,
      "failed_count": 2
    }
  },
  "duration_ms": 4523,
  "timestamp": "2025-10-16T12:05:00Z"
}
```

## Adding New Batch Processes

### **Step 1: Create the method**

```python
async def your_new_process(db: Session) -> Dict[str, Any]:
    """
    Description of what this process does
    
    Args:
        db: Database session
        
    Returns:
        Dict with relevant counts/stats
    """
    log.info("--- Your new process ---")
    
    # Your logic here
    
    return {
        "items_processed": count,
        "errors": error_count
    }
```

### **Step 2: Call from main worker**

```python
@router.post("/worker/queue_worker")
async def queue_worker(...):
    # ... security checks ...
    
    results = {}
    
    # Existing processes
    results["queued_pages"] = await process_queued_pages(db)
    
    # Add your new process
    results["your_process"] = await your_new_process(db)
    
    return final_result
```

### **Step 3: Deploy**

That's it! No new cron jobs, no new routes, just add the method.

## Benefits of This Architecture

### **1. Resource Efficiency**
- One cron job instead of N cron jobs
- Shared function invocation
- Shared timeout budget

### **2. Shared Infrastructure**
- Single security check
- Single logging setup
- Single error handling
- Single monitoring endpoint

### **3. Coordinated Execution**
- All processes run together
- Can share data/context
- Consistent timing
- Atomic success/failure

### **4. Easy Monitoring**
- One endpoint to monitor
- Aggregated results
- Single execution log
- Easy to see what ran when

### **5. Extensibility**
- Add new process = add one method
- No configuration changes needed
- Clear separation of concerns
- Each process isolated and testable

## Example Use Cases

### **Queued Pages Processing:**
```
Every 5 minutes:
  → Check for pages waiting for payment
  → Charge teams that added payment methods
  → Publish successfully charged pages
```

### **Dunning Emails (Future):**
```
Every 5 minutes:
  → Find teams with past_due subscriptions
  → If > 3 days since last email, send reminder
  → Track email sends
```

### **Analytics Aggregation (Future):**
```
Every 5 minutes:
  → Aggregate page view counts
  → Pre-compute team statistics
  → Update dashboard caches
```

### **Cleanup (Future):**
```
Every 5 minutes:
  → Delete verification codes > 30 days old
  → Remove expired OAuth states
  → Archive old page visits
```

## Performance Considerations

### **Timeout Budget:**
- Total time: 300 seconds (5 minutes)
- Must complete ALL processes within this time
- Add early termination if approaching timeout

### **Efficient Processing:**
```python
# Good: Early exit if nothing to do
queued_users = db.query(...).filter(...).all()
if len(queued_users) == 0:
    log.info("No queued pages, exiting early")
    return {"processed_count": 0}

# Good: Batch operations
db.query(...).update({...})  # Update many at once

# Avoid: Processing one at a time if you can batch
```

### **Monitoring:**
- Track duration per process
- Alert if total duration > 250 seconds (approaching limit)
- Log counts for each process

## Testing

### **Test Individual Process:**
```python
# In Python shell or test
from api.queue_worker import process_queued_pages
from database import SessionLocal

db = SessionLocal()
result = await process_queued_pages(db)
print(result)
```

### **Test Full Worker:**
```bash
# Call worker manually
curl -X POST http://localhost:8000/api/worker/queue_worker \
  -H "X-Worker-Secret: your-secret"
```

### **Test in Production:**
```bash
# Vercel dashboard → Crons → Run now
# Or call the Next.js endpoint:
curl -X GET https://your-app.vercel.app/api/worker/process-queued-pages \
  -H "Authorization: Bearer your-cron-secret"
```

## Files

### **Backend (FastAPI):**
- ✅ `api/queue_worker.py` - Main worker with batch processes
- ✅ `api/queue_status.py` - Queue status API for admins

### **Frontend (Next.js):**
- ✅ `app/api/worker/process-queued-pages/route.ts` - Cron trigger
- ✅ `vercel.json` - Cron configuration

### **Configuration:**
- ✅ Vercel cron: Every 5 minutes
- ✅ Max duration: 300 seconds
- ✅ Security: CRON_SECRET protected

## Summary

The worker has been refactored from a single-purpose "process queued pages" function into a modular batch processing system:

✅ **Modular design** - Each batch process is a separate method
✅ **Extensible** - Easy to add new processes  
✅ **Well-documented** - Clear comments for future developers
✅ **Future-ready** - Prepared for dunning emails and other processes
✅ **Resource efficient** - One cron job for all batch operations
✅ **Maintainable** - Clear separation of concerns

Adding a new batch process is now as simple as:
1. Write a new `async def` method
2. Call it from the main worker
3. Deploy!

No new routes, no new cron jobs, no configuration changes needed.

