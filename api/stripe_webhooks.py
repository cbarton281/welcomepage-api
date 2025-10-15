"""
Stripe webhook handler for processing Stripe events
"""
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session
from database import get_db
from models.team import Team
from services.stripe_service import StripeService
from utils.logger_factory import new_logger
import json

log = new_logger("stripe_webhooks")

router = APIRouter()

@router.post("/stripe/webhooks")
async def handle_stripe_webhook(
    request: Request,
    db: Session = Depends(get_db)
):
    """Handle Stripe webhook events"""
    try:
        # Get the raw body and signature
        body = await request.body()
        signature = request.headers.get("stripe-signature")
        
        if not signature:
            raise HTTPException(status_code=400, detail="Missing stripe-signature header")
        
        # Verify webhook signature
        event = StripeService.verify_webhook_signature(body, signature)
        
        event_type = event.get("type")
        event_id = event.get("id")
        # Top-level metadata for root-cause analysis
        log.info(
            f"Received Stripe webhook",
            extra={
                "event_id": event_id,
                "event_type": event_type,
                "created": event.get("created"),
                "api_version": event.get("api_version"),
                "livemode": event.get("livemode"),
                "request_id": event.get("request", {}).get("id") if isinstance(event.get("request"), dict) else event.get("request"),
                "object": event.get("object"),
                "customer": (
                    event.get("data", {})
                        .get("object", {})
                        .get("customer")
                ),
                "subscription_id": (
                    event.get("data", {})
                        .get("object", {})
                        .get("id")
                ) if event_type and "subscription" in event_type else None,
                "payload_short": str(event.get("data", {}))[:500]  # truncate large objects
            }
        )
        
        # Handle different event types
        if event["type"] == "customer.subscription.created":
            await handle_subscription_created(event, db)
        elif event["type"] == "customer.subscription.updated":
            await handle_subscription_updated(event, db)
        elif event["type"] == "customer.subscription.deleted":
            await handle_subscription_deleted(event, db)
        elif event["type"] == "customer.deleted":
            await handle_customer_deleted(event, db)
        elif event["type"] == "invoice.payment_succeeded":
            await handle_payment_succeeded(event, db)
        elif event["type"] == "invoice.payment_failed":
            await handle_payment_failed(event, db)
        else:
            log.info(f"Unhandled webhook event type: {event['type']}")
        
        return {"status": "success"}
        
    except Exception as e:
        log.error(f"Error processing Stripe webhook: {e}")
        raise HTTPException(status_code=500, detail="Webhook processing failed")

async def handle_subscription_created(event: dict, db: Session):
    """Handle subscription created event"""
    try:
        subscription = event["data"]["object"]
        customer_id = subscription["customer"]
        
        # Find team by customer ID
        team = db.query(Team).filter(Team.stripe_customer_id == customer_id).first()
        if not team:
            log.warning(f"No team found for customer {customer_id}")
            return
        
        # Update team with subscription info
        team.stripe_subscription_id = subscription["id"]
        
        # Store raw Stripe status for debugging and detailed messaging
        stripe_status = subscription["status"]
        team.stripe_subscription_status = stripe_status
        
        # Map Stripe status to our standardized values: "pro" or "free"
        # Stripe statuses: "active", "trialing", "past_due" → "pro"
        # Stripe statuses: "canceled", "incomplete", "incomplete_expired", "unpaid" → "free"
        if stripe_status in ["active", "trialing", "past_due"]:
            team.subscription_status = "pro"
        else:
            team.subscription_status = "free"
        
        db.commit()
        log.info(f"Updated team {team.public_id} with new subscription {subscription['id']}, stripe_status: {stripe_status}, subscription_status: {team.subscription_status}")
        
    except Exception as e:
        log.error(f"Error handling subscription created: {e}")
        db.rollback()

async def handle_subscription_updated(event: dict, db: Session):
    """Handle subscription updated event"""
    try:
        subscription = event["data"]["object"]
        subscription_id = subscription["id"]
        
        # Find team by subscription ID
        team = db.query(Team).filter(Team.stripe_subscription_id == subscription_id).first()
        if not team:
            log.warning(f"No team found for subscription {subscription_id}")
            return
        
        # Update subscription status
        # Store raw Stripe status for debugging and detailed messaging
        stripe_status = subscription["status"]
        team.stripe_subscription_status = stripe_status
        
        # Map Stripe status to our standardized values: "pro" or "free"
        if stripe_status in ["active", "trialing", "past_due"]:
            team.subscription_status = "pro"
        else:
            team.subscription_status = "free"
        
        db.commit()
        log.info(f"Updated subscription status for team {team.public_id}: stripe_status: {stripe_status}, subscription_status: {team.subscription_status}")
        
    except Exception as e:
        log.error(f"Error handling subscription updated: {e}")
        db.rollback()

async def handle_subscription_deleted(event: dict, db: Session):
    """Handle subscription deleted event"""
    try:
        subscription = event["data"]["object"]
        subscription_id = subscription["id"]
        
        # Find team by subscription ID
        team = db.query(Team).filter(Team.stripe_subscription_id == subscription_id).first()
        if not team:
            log.warning(f"No team found for subscription {subscription_id}")
            return
        
        # Clear subscription info
        team.stripe_subscription_id = None
        team.stripe_subscription_status = "canceled"  # Store raw Stripe status
        team.subscription_status = "free"  # Standardized to "free"
        
        db.commit()
        log.info(f"Cleared subscription info for team {team.public_id}, stripe_status: canceled, subscription_status: free")
        
    except Exception as e:
        log.error(f"Error handling subscription deleted: {e}")
        db.rollback()

async def handle_customer_deleted(event: dict, db: Session):
    """Handle customer deleted event"""
    try:
        customer = event["data"]["object"]
        customer_id = customer["id"]
        
        # Find team by customer ID
        team = db.query(Team).filter(Team.stripe_customer_id == customer_id).first()
        if not team:
            log.warning(f"No team found for customer {customer_id}")
            return
        
        # Clear customer and subscription info, reset to free plan
        team.stripe_customer_id = None
        team.stripe_subscription_id = None
        team.stripe_subscription_status = None  # Clear raw Stripe status
        team.subscription_status = "free"
        
        db.commit()
        log.info(f"Customer deleted for team {team.public_id}, reset to free plan")
        
    except Exception as e:
        log.error(f"Error handling customer deleted: {e}")
        db.rollback()

async def handle_payment_succeeded(event: dict, db: Session):
    """Handle successful payment event"""
    try:
        invoice = event["data"]["object"]
        customer_id = invoice["customer"]
        
        # Find team by customer ID
        team = db.query(Team).filter(Team.stripe_customer_id == customer_id).first()
        if not team:
            log.warning(f"No team found for customer {customer_id}")
            return
        
        log.info(f"Payment succeeded for team {team.public_id}, invoice {invoice['id']}")
        
    except Exception as e:
        log.error(f"Error handling payment succeeded: {e}")

async def handle_payment_failed(event: dict, db: Session):
    """Handle failed payment event"""
    try:
        invoice = event["data"]["object"]
        customer_id = invoice["customer"]
        
        # Find team by customer ID
        team = db.query(Team).filter(Team.stripe_customer_id == customer_id).first()
        if not team:
            log.warning(f"No team found for customer {customer_id}")
            return
        
        log.warning(f"Payment failed for team {team.public_id}, invoice {invoice['id']}")
        
        # You might want to send notifications or take other actions here
        
    except Exception as e:
        log.error(f"Error handling payment failed: {e}")
