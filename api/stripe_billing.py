"""
Stripe billing API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from database import get_db
from models.team import Team
from services.stripe_service import StripeService
from utils.jwt_auth import require_roles
from utils.logger_factory import new_logger
from typing import Dict, Any, List
import stripe

log = new_logger("stripe_billing")

router = APIRouter()

# Stripe price IDs - these should be set in environment variables
STRIPE_PRO_PRICE_ID = "price_1234567890"  # Replace with actual price ID

@router.get("/teams/{team_public_id}/billing/status")
async def get_billing_status(
    team_public_id: str,
    current_user=Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db)
):
    """Get team's billing status and subscription details"""
    try:
        # Get team from database
        team = db.query(Team).filter(Team.public_id == team_public_id).first()
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        
        # If no Stripe customer, return free plan status
        if not team.stripe_customer_id:
            return {
                "plan": "free",
                "status": "active",
                "welcomepages_limit": 3,
                "welcomepages_used": len(team.users),
                "pricing": {
                    "amount": 0,
                    "currency": "usd",
                    "interval": "forever"
                }
            }
        
        # Get fresh data from Stripe
        customer = await StripeService.get_customer(team.stripe_customer_id)
        
        if not team.stripe_subscription_id:
            # Customer exists but no active subscription
            return {
                "plan": "free",
                "status": "active",
                "welcomepages_limit": 3,
                "welcomepages_used": len(team.users),
                "pricing": {
                    "amount": 0,
                    "currency": "usd",
                    "interval": "forever"
                }
            }
        
        # Get subscription details
        subscription = await StripeService.get_subscription(team.stripe_subscription_id)
        
        return {
            "plan": "pro",
            "status": subscription.status,
            "welcomepages_limit": "unlimited",
            "welcomepages_used": len(team.users),
            "pricing": {
                "amount": subscription.items.data[0].price.unit_amount,
                "currency": subscription.items.data[0].price.currency,
                "interval": subscription.items.data[0].price.recurring.interval
            },
            "current_period_start": subscription.current_period_start,
            "current_period_end": subscription.current_period_end,
            "cancel_at_period_end": subscription.cancel_at_period_end
        }
        
    except stripe.error.StripeError as e:
        log.error(f"Stripe error getting billing status: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving billing information")
    except Exception as e:
        log.error(f"Error getting billing status: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/teams/{team_public_id}/billing/upgrade")
async def upgrade_subscription(
    team_public_id: str,
    request_data: Dict[str, Any],
    current_user=Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db)
):
    """Upgrade team to Pro subscription"""
    try:
        # Get team from database
        team = db.query(Team).filter(Team.public_id == team_public_id).first()
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        
        email = request_data.get("email")
        if not email:
            raise HTTPException(status_code=400, detail="Email is required")
        
        # Create or get Stripe customer
        if not team.stripe_customer_id:
            customer = await StripeService.create_customer(
                email=email,
                name=team.organization_name,
                team_public_id=team_public_id
            )
            team.stripe_customer_id = customer.id
        else:
            customer = await StripeService.get_customer(team.stripe_customer_id)
        
        # Create subscription
        subscription = await StripeService.create_subscription(
            customer_id=team.stripe_customer_id,
            price_id=STRIPE_PRO_PRICE_ID,
            team_public_id=team_public_id
        )
        
        # Update team with subscription info
        team.stripe_subscription_id = subscription.id
        team.subscription_status = subscription.status
        
        db.commit()
        
        return {
            "success": True,
            "subscription_id": subscription.id,
            "status": subscription.status,
            "client_secret": subscription.latest_invoice.payment_intent.client_secret
        }
        
    except stripe.error.StripeError as e:
        log.error(f"Stripe error upgrading subscription: {e}")
        raise HTTPException(status_code=500, detail="Error creating subscription")
    except Exception as e:
        log.error(f"Error upgrading subscription: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/teams/{team_public_id}/billing/downgrade")
async def downgrade_subscription(
    team_public_id: str,
    current_user=Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db)
):
    """Downgrade team to Free plan"""
    try:
        # Get team from database
        team = db.query(Team).filter(Team.public_id == team_public_id).first()
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        
        if not team.stripe_subscription_id:
            raise HTTPException(status_code=400, detail="No active subscription to cancel")
        
        # Cancel subscription
        subscription = await StripeService.cancel_subscription(team.stripe_subscription_id)
        
        # Update team
        team.stripe_subscription_id = None
        team.subscription_status = "canceled"
        
        db.commit()
        
        return {
            "success": True,
            "status": "canceled",
            "message": "Subscription canceled successfully"
        }
        
    except stripe.error.StripeError as e:
        log.error(f"Stripe error downgrading subscription: {e}")
        raise HTTPException(status_code=500, detail="Error canceling subscription")
    except Exception as e:
        log.error(f"Error downgrading subscription: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/teams/{team_public_id}/billing/history")
async def get_billing_history(
    team_public_id: str,
    current_user=Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db)
):
    """Get team's billing history"""
    try:
        # Get team from database
        team = db.query(Team).filter(Team.public_id == team_public_id).first()
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        
        if not team.stripe_customer_id:
            return {"invoices": []}
        
        # Get invoices from Stripe
        invoices = await StripeService.get_invoices(team.stripe_customer_id, limit=20)
        
        # Format invoices for frontend
        formatted_invoices = []
        for invoice in invoices:
            formatted_invoices.append({
                "id": invoice.id,
                "number": invoice.number,
                "status": invoice.status,
                "amount_paid": invoice.amount_paid,
                "amount_due": invoice.amount_due,
                "currency": invoice.currency,
                "created": invoice.created,
                "period_start": invoice.period_start,
                "period_end": invoice.period_end,
                "hosted_invoice_url": invoice.hosted_invoice_url,
                "invoice_pdf": invoice.invoice_pdf
            })
        
        return {"invoices": formatted_invoices}
        
    except stripe.error.StripeError as e:
        log.error(f"Stripe error getting billing history: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving billing history")
    except Exception as e:
        log.error(f"Error getting billing history: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/teams/{team_public_id}/billing/payment-methods")
async def get_payment_methods(
    team_public_id: str,
    current_user=Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db)
):
    """Get team's payment methods"""
    try:
        # Get team from database
        team = db.query(Team).filter(Team.public_id == team_public_id).first()
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        
        if not team.stripe_customer_id:
            return {"payment_methods": []}
        
        # Get payment methods from Stripe
        payment_methods = await StripeService.get_payment_methods(team.stripe_customer_id)
        
        # Format payment methods for frontend
        formatted_methods = []
        for pm in payment_methods:
            if pm.type == "card":
                formatted_methods.append({
                    "id": pm.id,
                    "type": pm.type,
                    "card": {
                        "brand": pm.card.brand,
                        "last4": pm.card.last4,
                        "exp_month": pm.card.exp_month,
                        "exp_year": pm.card.exp_year
                    },
                    "is_default": pm.id == team.stripe_customer_id  # This would need to be checked against customer's default
                })
        
        return {"payment_methods": formatted_methods}
        
    except stripe.error.StripeError as e:
        log.error(f"Stripe error getting payment methods: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving payment methods")
    except Exception as e:
        log.error(f"Error getting payment methods: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/teams/{team_public_id}/billing/payment-methods")
async def add_payment_method(
    team_public_id: str,
    request_data: Dict[str, Any],
    current_user=Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db)
):
    """Add a new payment method"""
    try:
        # Get team from database
        team = db.query(Team).filter(Team.public_id == team_public_id).first()
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        
        payment_method_id = request_data.get("payment_method_id")
        if not payment_method_id:
            raise HTTPException(status_code=400, detail="Payment method ID is required")
        
        if not team.stripe_customer_id:
            raise HTTPException(status_code=400, detail="No Stripe customer found")
        
        # Attach payment method to customer
        payment_method = await StripeService.create_payment_method(
            customer_id=team.stripe_customer_id,
            payment_method_id=payment_method_id
        )
        
        # Set as default if it's the first payment method
        existing_methods = await StripeService.get_payment_methods(team.stripe_customer_id)
        if len(existing_methods) <= 1:  # This is the first/only method
            await StripeService.set_default_payment_method(
                customer_id=team.stripe_customer_id,
                payment_method_id=payment_method_id
            )
        
        return {
            "success": True,
            "payment_method": {
                "id": payment_method.id,
                "type": payment_method.type,
                "card": {
                    "brand": payment_method.card.brand,
                    "last4": payment_method.card.last4,
                    "exp_month": payment_method.card.exp_month,
                    "exp_year": payment_method.card.exp_year
                }
            }
        }
        
    except stripe.error.StripeError as e:
        log.error(f"Stripe error adding payment method: {e}")
        raise HTTPException(status_code=500, detail="Error adding payment method")
    except Exception as e:
        log.error(f"Error adding payment method: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.delete("/teams/{team_public_id}/billing/payment-methods/{payment_method_id}")
async def remove_payment_method(
    team_public_id: str,
    payment_method_id: str,
    current_user=Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db)
):
    """Remove a payment method"""
    try:
        # Get team from database
        team = db.query(Team).filter(Team.public_id == team_public_id).first()
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        
        # Detach payment method
        await StripeService.detach_payment_method(payment_method_id)
        
        return {"success": True, "message": "Payment method removed successfully"}
        
    except stripe.error.StripeError as e:
        log.error(f"Stripe error removing payment method: {e}")
        raise HTTPException(status_code=500, detail="Error removing payment method")
    except Exception as e:
        log.error(f"Error removing payment method: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
