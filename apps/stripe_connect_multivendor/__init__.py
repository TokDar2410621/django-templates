"""stripe_connect_multivendor — Stripe Connect payouts to multiple vendors.

Rewritten from SendMeNow's ``apps/shop`` (Partner / Affiliate / payout
ledger). See README.md for integration. The calling project owns its
Order / OrderItem / Product models and triggers payouts from its own
order-paid handler — this template only handles the Connect side.
"""
default_app_config = "stripe_connect_multivendor.apps.StripeConnectMultivendorConfig"
