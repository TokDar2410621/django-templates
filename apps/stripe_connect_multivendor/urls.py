"""URL routes for the Stripe Connect multivendor template.

Mount under any prefix you like in your ``config/urls.py``::

    path("api/payouts/", include("stripe_connect_multivendor.urls")),

The Stripe webhook endpoint MUST match the URL registered in the
Stripe dashboard. If you mount under ``/api/payouts/``, the webhook
URL is ``/api/payouts/webhooks/stripe/``.
"""
from __future__ import annotations

from django.urls import path

from .views import (
    PartnerConnectCallbackView,
    PartnerConnectStartView,
    PartnerPayoutsView,
    StripeWebhookView,
)

app_name = "stripe_connect_multivendor"

urlpatterns = [
    path("connect/start/", PartnerConnectStartView.as_view(), name="connect-start"),
    path("connect/callback/", PartnerConnectCallbackView.as_view(), name="connect-callback"),
    path("payouts/", PartnerPayoutsView.as_view(), name="payouts"),
    path("webhooks/stripe/", StripeWebhookView.as_view(), name="stripe-webhook"),
]
