
"""
Batch worker for scheduled background tasks

This worker is called by Vercel cron and handles multiple types of batch processes:
- Process queued page publications (charge and publish pages waiting for payment)
- Send dunning emails (future)
- Cleanup expired data (future)
- Analytics aggregation (future)

The worker is designed to be extensible - new batch processes can be added as separate
methods and called from the main worker endpoint.
"""

from fastapi import APIRouter, HTTPException, Request, Depends
from sqlalchemy.orm import Session
from sqlalchemy import and_
from database import get_db
from models.welcomepage_user import WelcomepageUser
from models.team import Team
from utils.logger_factory import new_logger
from datetime import datetime, timezone
from typing import Dict, Any
import os

router = APIRouter()

log = new_logger("queue_worker")


async def process_queued_pages(db: Session) -> Dict[str, Any]:
    """
    Process queued welcomepage publications
    
    Finds pages that are queued for payment, charges teams that now have
    payment methods, and publishes successfully charged pages.
    
    Args:
        db: Database session
        
    Returns:
        Dict with processed_count, failed_count, skipped_count
    """
    log.info("--- Processing queued pages ---")
    
    # Find all users with queued pages
    queued_users = db.query(WelcomepageUser).filter(
        WelcomepageUser.publish_queued == True
    ).all()
    
    log.info(f"Found {len(queued_users)} queued pages to process")
    
    processed_count = 0
    failed_count = 0
    skipped_count = 0
    
    # Group queued users by team for efficient processing
    teams_with_queued = {}
    for user in queued_users:
        if user.team_id not in teams_with_queued:
            teams_with_queued[user.team_id] = []
        teams_with_queued[user.team_id].append(user)
    
    log.info(f"Processing queued pages across {len(teams_with_queued)} teams")
    
    # Process each team's queued pages
    for team_id, users in teams_with_queued.items():
        team = db.query(Team).filter_by(id=team_id).first()
        if not team:
            log.warning(f"Team {team_id} not found, skipping {len(users)} queued pages")
            skipped_count += len(users)
            continue
        
        log.info(f"Processing team {team.public_id}: {len(users)} queued pages")
        
        # Check if team has payment method
        if not team.stripe_customer_id:
            log.info(f"Team {team.public_id} still has no payment method, skipping")
            skipped_count += len(users)
            continue
        
        # Team has payment method - process queued pages
        from api.stripe_billing import charge_for_welcomepage
        from services.slack_publish_service import SlackPublishService
        
        for user in users:
            try:
                log.info(f"Processing queued page for user {user.public_id}")
                
                # Charge $7.99 for the page
                charge_result = await charge_for_welcomepage(
                    team_public_id=team.public_id,
                    user_public_id=user.public_id,
                    db=db
                )
                
                if not charge_result.get("success"):
                    log.error(f"Payment failed for queued page {user.public_id}: {charge_result}")
                    failed_count += 1
                    continue
                
                log.info(f"Payment successful for {user.public_id}, publishing to Slack")
                
                # Publish to Slack
                publish_result = SlackPublishService.publish_welcomepage(
                    user_public_id=user.public_id,
                    custom_message="",
                    db=db
                )
                
                if not publish_result.get("success"):
                    log.error(f"Publish failed for {user.public_id}: {publish_result}")
                    failed_count += 1
                    continue
                
                # Mark as successfully processed
                user.publish_queued = False
                user.is_draft = False
                user.queued_at = None
                db.commit()
                
                log.info(f"Successfully processed queued page for {user.public_id}")
                processed_count += 1
                
            except Exception as e:
                log.error(f"Error processing queued page for {user.public_id}: {str(e)}")
                db.rollback()
                failed_count += 1
    
    log.info(f"Queued pages processing complete: {processed_count} processed, {failed_count} failed, {skipped_count} skipped")
    
    return {
        "processed_count": processed_count,
        "failed_count": failed_count,
        "skipped_count": skipped_count
    }


async def send_dunning_emails(db: Session) -> Dict[str, Any]:
    """
    Send dunning emails for failed payments (future implementation)
    
    Finds teams with past_due subscriptions and sends reminder emails
    to admins to update their payment methods.
    
    Args:
        db: Database session
        
    Returns:
        Dict with emails_sent, failed_count
    """
    log.info("--- Sending dunning emails (not yet implemented) ---")
    
    # TODO: Implement dunning email logic
    # 1. Find teams with stripe_subscription_status = 'past_due'
    # 2. Check when last dunning email was sent
    # 3. Send email to team admins
    # 4. Track email send success/failure
    
    return {
        "emails_sent": 0,
        "failed_count": 0
    }


@router.post("/worker/queue_worker")
async def queue_worker(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Batch worker for scheduled background tasks
    
    This worker handles multiple types of batch processes:
    - Process queued page publications
    - Send dunning emails (future)
    - Cleanup expired data (future)
    - Other recurring batch operations
    
    Security: Protected by X-Worker-Secret header (verified against CRON_SECRET)
    
    Returns:
        Summary of all batch processes executed with counts and timing
    """
    start_time = datetime.now(timezone.utc)
    log.info("=== Starting batch worker execution ===")
    
    try:
        # Security: Verify worker secret
        worker_secret = request.headers.get('x-worker-secret')
        expected_secret = os.getenv('CRON_SECRET')
        
        if not expected_secret:
            log.error("CRON_SECRET not configured")
            raise HTTPException(status_code=500, detail="Service configuration error")
        
        if worker_secret != expected_secret:
            log.warning("Unauthorized worker execution attempt")
            raise HTTPException(status_code=401, detail="Unauthorized")
        
        log.info("Worker authorization verified")
        
        # Execute all batch processes
        results = {}
        
        # 1. Process queued pages
        queued_pages_result = await process_queued_pages(db)
        results["queued_pages"] = queued_pages_result
        
        # 2. Send dunning emails (future - currently stub)
        # dunning_result = await send_dunning_emails(db)
        # results["dunning_emails"] = dunning_result
        
        # 3. Add more batch processes here as needed
        # cleanup_result = await cleanup_expired_data(db)
        # results["cleanup"] = cleanup_result
        
        log.info("=== Batch worker execution complete ===")
        duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
        
        final_result = {
            "success": True,
            "results": results,
            "duration_ms": duration_ms,
            "timestamp": start_time.isoformat()
        }
        
        log.info(f"Worker final result: {final_result}")
        return final_result
        
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Worker execution failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Worker failed: {str(e)}")

