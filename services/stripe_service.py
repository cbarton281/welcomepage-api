"""
Stripe service for handling all Stripe API interactions
"""
import stripe
import os
from typing import Dict, List, Optional, Any
from utils.logger_factory import new_logger

log = new_logger("stripe_service")

# Initialize Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

if not stripe.api_key:
    raise ValueError("STRIPE_SECRET_KEY environment variable is required")

class StripeService:
    """Service for handling Stripe operations"""
    
    @staticmethod
    async def create_customer(email: str, name: str, team_public_id: str) -> Dict[str, Any]:
        """Create a new Stripe customer"""
        try:
            customer = stripe.Customer.create(
                email=email,
                name=name,
                metadata={
                    "team_public_id": team_public_id,
                    "source": "welcomepage"
                }
            )
            log.info(f"Created Stripe customer {customer.id} for team {team_public_id}")
            return customer
        except stripe.error.StripeError as e:
            log.error(f"Error creating Stripe customer: {e}")
            raise
    
    @staticmethod
    async def get_customer(customer_id: str) -> Dict[str, Any]:
        """Get Stripe customer by ID"""
        try:
            customer = stripe.Customer.retrieve(customer_id)
            return customer
        except stripe.error.StripeError as e:
            log.error(f"Error retrieving Stripe customer {customer_id}: {e}")
            raise
    
    @staticmethod
    async def create_subscription(
        customer_id: str, 
        price_id: str, 
        team_public_id: str
    ) -> Dict[str, Any]:
        """Create a new subscription"""
        try:
            subscription = stripe.Subscription.create(
                customer=customer_id,
                items=[{"price": price_id}],
                metadata={
                    "team_public_id": team_public_id,
                    "source": "welcomepage"
                },
                expand=["latest_invoice.payment_intent"]
            )
            log.info(f"Created subscription {subscription.id} for team {team_public_id}")
            return subscription
        except stripe.error.StripeError as e:
            log.error(f"Error creating subscription: {e}")
            raise
    
    @staticmethod
    async def get_subscription(subscription_id: str) -> Dict[str, Any]:
        """Get subscription by ID"""
        try:
            subscription = stripe.Subscription.retrieve(subscription_id)
            return subscription
        except stripe.error.StripeError as e:
            log.error(f"Error retrieving subscription {subscription_id}: {e}")
            raise
    
    @staticmethod
    async def cancel_subscription(subscription_id: str) -> Dict[str, Any]:
        """Cancel a subscription"""
        try:
            subscription = stripe.Subscription.cancel(subscription_id)
            log.info(f"Cancelled subscription {subscription_id}")
            return subscription
        except stripe.error.StripeError as e:
            log.error(f"Error cancelling subscription {subscription_id}: {e}")
            raise
    
    @staticmethod
    async def get_payment_methods(customer_id: str) -> List[Dict[str, Any]]:
        """Get customer's payment methods"""
        try:
            payment_methods = stripe.PaymentMethod.list(
                customer=customer_id,
                type="card"
            )
            return payment_methods.data
        except stripe.error.StripeError as e:
            log.error(f"Error retrieving payment methods for customer {customer_id}: {e}")
            raise
    
    @staticmethod
    async def get_default_payment_method(customer_id: str) -> Optional[Dict[str, Any]]:
        """Get customer's default payment method"""
        try:
            customer = await StripeService.get_customer(customer_id)
            if customer.invoice_settings.default_payment_method:
                payment_method = stripe.PaymentMethod.retrieve(
                    customer.invoice_settings.default_payment_method
                )
                return payment_method
            return None
        except stripe.error.StripeError as e:
            log.error(f"Error retrieving default payment method for customer {customer_id}: {e}")
            raise
    
    @staticmethod
    async def get_invoices(customer_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get customer's invoices"""
        try:
            invoices = stripe.Invoice.list(
                customer=customer_id,
                limit=limit
            )
            return invoices.data
        except stripe.error.StripeError as e:
            log.error(f"Error retrieving invoices for customer {customer_id}: {e}")
            raise
    
    @staticmethod
    async def get_invoice(invoice_id: str) -> Dict[str, Any]:
        """Get specific invoice by ID"""
        try:
            invoice = stripe.Invoice.retrieve(invoice_id)
            return invoice
        except stripe.error.StripeError as e:
            log.error(f"Error retrieving invoice {invoice_id}: {e}")
            raise
    
    @staticmethod
    async def create_payment_method(
        customer_id: str, 
        payment_method_id: str
    ) -> Dict[str, Any]:
        """Attach a payment method to a customer"""
        try:
            payment_method = stripe.PaymentMethod.attach(
                payment_method_id,
                customer=customer_id
            )
            log.info(f"Attached payment method {payment_method_id} to customer {customer_id}")
            return payment_method
        except stripe.error.StripeError as e:
            log.error(f"Error attaching payment method {payment_method_id}: {e}")
            raise
    
    @staticmethod
    async def set_default_payment_method(
        customer_id: str, 
        payment_method_id: str
    ) -> Dict[str, Any]:
        """Set default payment method for customer"""
        try:
            customer = stripe.Customer.modify(
                customer_id,
                invoice_settings={
                    "default_payment_method": payment_method_id
                }
            )
            log.info(f"Set default payment method {payment_method_id} for customer {customer_id}")
            return customer
        except stripe.error.StripeError as e:
            log.error(f"Error setting default payment method {payment_method_id}: {e}")
            raise
    
    @staticmethod
    async def detach_payment_method(payment_method_id: str) -> Dict[str, Any]:
        """Detach payment method from customer"""
        try:
            payment_method = stripe.PaymentMethod.detach(payment_method_id)
            log.info(f"Detached payment method {payment_method_id}")
            return payment_method
        except stripe.error.StripeError as e:
            log.error(f"Error detaching payment method {payment_method_id}: {e}")
            raise
    
    @staticmethod
    def verify_webhook_signature(payload: bytes, signature: str) -> Dict[str, Any]:
        """Verify Stripe webhook signature"""
        try:
            event = stripe.Webhook.construct_event(
                payload, signature, STRIPE_WEBHOOK_SECRET
            )
            return event
        except ValueError as e:
            log.error(f"Invalid payload: {e}")
            raise
        except stripe.error.SignatureVerificationError as e:
            log.error(f"Invalid signature: {e}")
            raise
