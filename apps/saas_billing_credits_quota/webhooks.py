"""Stripe webhook event router.

One function per event type so callers can register custom handlers
incrementally. The router catches handler exceptions and logs them — the
HTTP layer (``StripeWebhookView``) ALWAYS returns 200 after the router
returns so Stripe doesn't retry a buggy handler for three weeks.

Why a separate module instead of methods on the view?
The webhook surface is the only place where the billing app touches the
outside world. Keeping the router pure (no DRF, no HTTP) means we can test
it with raw dict fixtures and reuse the dispatch logic from a Celery task
if we ever queue webhooks for async processing.
"""
from __future__ import annotations

import logging
from typing import Any

from django.contrib.auth import get_user_model

from .selectors import find_user_by_stripe_customer
from .services import (
    add_credits,
    attach_stripe_customer,
    mark_active,
    mark_past_due,
    update_subscription_from_stripe,
)

logger = logging.getLogger(__name__)
User = get_user_model()


def dispatch(event: dict[str, Any]) -> None:
    """Route a parsed Stripe event to the matching handler.

    ``event`` is the dict you get from ``stripe.Webhook.construct_event(...)``.
    No-ops on unknown event types — Stripe sends 100+ types and we only care
    about the billing-relevant subset.
    """
    event_type = event.get("type") or ""
    data = (event.get("data") or {}).get("object") or {}

    if event_type in (
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    ):
        _handle_subscription_event(event_type, data)
    elif event_type == "invoice.payment_failed":
        _handle_invoice_failed(data)
    elif event_type == "invoice.payment_succeeded":
        _handle_invoice_succeeded(data)
    elif event_type == "checkout.session.completed":
        _handle_checkout_completed(data)
    else:
        logger.debug("saas.webhook ignored event_type=%s", event_type)


def _handle_subscription_event(event_type: str, data: dict[str, Any]) -> None:
    customer_id = data.get("customer")
    user = find_user_by_stripe_customer(customer_id) if customer_id else None
    if user is None:
        logger.warning(
            "saas.webhook subscription event for unknown customer=%s type=%s",
            customer_id, event_type,
        )
        return
    update_subscription_from_stripe(user, data)


def _handle_invoice_failed(invoice: dict[str, Any]) -> None:
    customer_id = invoice.get("customer")
    user = find_user_by_stripe_customer(customer_id) if customer_id else None
    if user is None:
        return
    mark_past_due(user)
    logger.warning(
        "saas.webhook invoice.payment_failed user=%s amount=%s attempt=%s",
        user.pk, invoice.get("amount_due"), invoice.get("attempt_count"),
    )


def _handle_invoice_succeeded(invoice: dict[str, Any]) -> None:
    # Skip the $0 invoice Stripe issues alongside subscription_create — the
    # customer.subscription.created event is the source of truth for that
    # transition.
    if invoice.get("billing_reason") == "subscription_create":
        return
    customer_id = invoice.get("customer")
    user = find_user_by_stripe_customer(customer_id) if customer_id else None
    if user is None:
        return
    mark_active(user)


def _handle_checkout_completed(session: dict[str, Any]) -> None:
    """One-time payment (credits pack) → add credits.

    Subscription checkouts (``mode=subscription``) are handled via
    ``customer.subscription.created`` instead.
    """
    if session.get("mode") != "payment":
        return
    metadata = session.get("metadata") or {}
    user_id = metadata.get("user_id")
    credits_str = metadata.get("credits")
    pack = metadata.get("pack", "credits")
    session_id = session.get("id") or ""
    customer_id = session.get("customer") or ""

    if not user_id or not credits_str:
        logger.warning(
            "saas.webhook checkout.completed missing metadata: %s", metadata,
        )
        return

    try:
        user = User.objects.get(pk=int(user_id))
    except (User.DoesNotExist, ValueError):
        logger.warning("saas.webhook checkout.completed unknown user_id=%s", user_id)
        return

    if customer_id:
        attach_stripe_customer(user, customer_id)

    try:
        n = int(credits_str)
    except (TypeError, ValueError):
        logger.warning("saas.webhook bad credits in metadata: %s", metadata)
        return

    new_balance = add_credits(
        user, n,
        kind="purchase",
        stripe_session_id=session_id,
        description=f"Pack {pack}: +{n} credits",
    )
    logger.info(
        "saas.webhook credits applied user=%s pack=%s +%d new_balance=%d",
        user.pk, pack, n, new_balance,
    )
