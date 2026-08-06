"""Billing URLs — mount on ``/api/billing/`` in your project.

Suggested wiring::

    # config/urls.py
    urlpatterns = [
        ...
        path("api/billing/", include("saas_billing_credits_quota.urls")),
    ]

The Stripe webhook lives at ``/api/billing/stripe/webhook/`` — register that
URL on the Stripe dashboard.
"""
from django.urls import path

from .views import (
    ConsumeView,
    MeSubscriptionView,
    StripeCheckoutView,
    StripeWebhookView,
)


app_name = "saas_billing_credits_quota"

urlpatterns = [
    path("me/", MeSubscriptionView.as_view(), name="billing-me"),
    path("consume/", ConsumeView.as_view(), name="billing-consume"),
    path("checkout/", StripeCheckoutView.as_view(), name="billing-checkout"),
    path("stripe/webhook/", StripeWebhookView.as_view(), name="billing-stripe-webhook"),
]
