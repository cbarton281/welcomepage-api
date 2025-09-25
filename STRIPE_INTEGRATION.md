# Stripe Integration Setup

This document outlines the Stripe integration implementation for the Welcomepage application.

## Overview

The integration follows a Stripe-first approach where minimal data is stored in the database and most payment information is fetched directly from Stripe's API.

## Database Changes

### Team Model Updates
Added the following fields to the `teams` table:
- `stripe_customer_id` (VARCHAR(255), unique, indexed)
- `stripe_subscription_id` (VARCHAR(255), unique, indexed) 
- `subscription_status` (VARCHAR(50))

### Migration
Run the migration: `20250841_add_stripe_integration_to_team.py`

## Environment Variables

Add these to your `.env` file:

```bash
# Stripe Configuration
STRIPE_SECRET_KEY=sk_test_your_stripe_secret_key_here
STRIPE_PUBLISHABLE_KEY=pk_test_your_stripe_publishable_key_here
STRIPE_WEBHOOK_SECRET=whsec_your_webhook_secret_here
STRIPE_WELCOMEPAGE_PRICE_ID=price_your_welcomepage_price_id_here
STRIPE_HOSTING_PRICE_ID=price_your_hosting_price_id_here
```

## API Endpoints

### FastAPI Backend
- `GET /api/teams/{team_id}/billing/status` - Get billing status
- `POST /api/teams/{team_id}/billing/upgrade` - Capture payment method (no charge)
- `POST /api/teams/{team_id}/billing/confirm-payment-method` - Confirm captured payment method
- `POST /api/teams/{team_id}/billing/charge-welcomepage` - Charge $7.99 for new welcomepage
- `POST /api/teams/{team_id}/billing/downgrade` - Downgrade to Free
- `GET /api/teams/{team_id}/billing/history` - Get billing history
- `GET /api/teams/{team_id}/billing/payment-methods` - Get payment methods
- `POST /api/teams/{team_id}/billing/payment-methods` - Add payment method
- `DELETE /api/teams/{team_id}/billing/payment-methods/{pm_id}` - Remove payment method
- `POST /api/stripe/webhooks` - Stripe webhook handler

### Next.js API Routes
- `GET /api/wp/team/billing/status`
- `POST /api/wp/team/billing/upgrade`
- `POST /api/wp/team/billing/downgrade`
- `GET /api/wp/team/billing/history`
- `GET /api/wp/team/billing/payment-methods`
- `POST /api/wp/team/billing/payment-methods`
- `DELETE /api/wp/team/billing/payment-methods/[paymentMethodId]`

## Stripe Setup

1. **Create Stripe Account**: Sign up at stripe.com
2. **Get API Keys**: From Stripe Dashboard > Developers > API keys
3. **Create Products & Prices**: 
   - Create a "Welcomepage Creation" product with $7.99 one-time price
   - Create a "Hosting Plan" product with $25.00 monthly recurring price
   - Copy the price IDs to `STRIPE_WELCOMEPAGE_PRICE_ID` and `STRIPE_HOSTING_PRICE_ID`
4. **Set up Webhooks**:
   - Add endpoint: `https://yourdomain.com/api/stripe/webhooks`
   - Select events: `customer.subscription.*`, `invoice.payment_*`
   - Copy webhook secret to `STRIPE_WEBHOOK_SECRET`

## Frontend Integration

The existing UI components have been updated to use real API endpoints:

- **Team Settings Page**: Fetches real billing data on load
- **Upgrade Modal**: Calls upgrade API with email
- **Downgrade Modal**: Calls downgrade API
- **Billing History**: Displays real invoices from Stripe
- **Payment Methods**: Shows real payment methods from Stripe

## Security

- All API endpoints require ADMIN role
- JWT authentication for FastAPI calls
- Stripe webhook signature verification
- No sensitive payment data stored in database

## Testing

Use Stripe test mode with test cards:
- `4242424242424242` - Successful payment
- `4000000000000002` - Declined payment
- `4000000000009995` - Insufficient funds

## Deployment

1. Set environment variables in production
2. Run database migration
3. Update Stripe webhook URL to production domain
4. Test with real Stripe test mode before going live
