"""Stripe webhook dispatch tests — no actual Stripe API calls.

We feed the dispatcher hand-built event dicts that match the shape of real
Stripe events. The signature verification step lives in the HTTP view layer
(``StripeWebhookView``), not in ``webhooks.dispatch``, so tests can pass
"trusted" dicts directly.
"""
from __future__ import annotations

import pytest

from saas_billing_credits_quota.models import CreditTransaction, Subscription
from saas_billing_credits_quota.selectors import (
    get_balance,
    get_or_create_subscription,
)
from saas_billing_credits_quota.services import attach_stripe_customer
from saas_billing_credits_quota.webhooks import dispatch


@pytest.mark.django_db
def test_subscription_updated_event_mirrors_status(user, plan_limits):
    """A customer.subscription.updated event flips our row's status."""
    sub = get_or_create_subscription(user)
    sub.stripe_customer_id = "cus_test123"
    sub.save()

    dispatch({
        "id": "evt_1",
        "type": "customer.subscription.updated",
        "data": {"object": {
            "id": "sub_test1",
            "customer": "cus_test123",
            "status": "past_due",
            "cancel_at_period_end": True,
            "items": {"data": []},
        }},
    })
    sub.refresh_from_db()
    assert sub.status == "past_due"
    assert sub.cancel_at_period_end is True
    assert sub.stripe_subscription_id == "sub_test1"


@pytest.mark.django_db
def test_subscription_deleted_event_downgrades_to_free(user, plan_limits, settings):
    settings.SAAS_DEFAULT_PLAN = "free"
    sub = get_or_create_subscription(user)
    sub.plan = "pro"
    sub.stripe_customer_id = "cus_test456"
    sub.save()

    dispatch({
        "id": "evt_2",
        "type": "customer.subscription.deleted",
        "data": {"object": {
            "id": "sub_test2",
            "customer": "cus_test456",
            "status": "canceled",
            "items": {"data": []},
        }},
    })
    sub.refresh_from_db()
    assert sub.status == "canceled"
    assert sub.plan == "free"


@pytest.mark.django_db
def test_checkout_completed_adds_credits(user, plan_limits):
    """checkout.session.completed (mode=payment) credits the user's balance."""
    assert get_balance(user) == 0
    dispatch({
        "id": "evt_3",
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": "cs_test_abc",
            "mode": "payment",
            "customer": "cus_new",
            "metadata": {
                "user_id": str(user.pk),
                "pack": "small",
                "credits": "10",
            },
        }},
    })
    assert get_balance(user) == 10
    # Customer id was attached as a side effect
    sub = Subscription.objects.get(user=user)
    assert sub.stripe_customer_id == "cus_new"


@pytest.mark.django_db
def test_checkout_completed_is_idempotent(user, plan_limits):
    """Re-delivering the same checkout.session.completed event is a NO-OP."""
    event = {
        "id": "evt_4",
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": "cs_test_same_session",
            "mode": "payment",
            "customer": "cus_idem",
            "metadata": {
                "user_id": str(user.pk),
                "pack": "small",
                "credits": "7",
            },
        }},
    }
    dispatch(event)
    dispatch(event)
    dispatch(event)
    assert get_balance(user) == 7
    # And only one purchase ledger row exists
    assert CreditTransaction.objects.filter(
        user=user, kind="purchase", stripe_session_id="cs_test_same_session",
    ).count() == 1


@pytest.mark.django_db
def test_unknown_event_type_is_noop(user, plan_limits):
    """Stripe sends 100+ event types; we ignore the ones we don't care about."""
    dispatch({"id": "evt_ignore", "type": "ping", "data": {"object": {}}})
    # No subscription auto-created (no side effects)
    assert not Subscription.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_subscription_event_for_unknown_customer_is_noop(user, plan_limits):
    """Webhook arrives before our row has the customer_id attached → log + drop."""
    dispatch({
        "id": "evt_5",
        "type": "customer.subscription.updated",
        "data": {"object": {
            "id": "sub_ghost",
            "customer": "cus_does_not_exist",
            "status": "active",
            "items": {"data": []},
        }},
    })
    # No subscription created or modified
    assert not Subscription.objects.filter(stripe_customer_id="cus_does_not_exist").exists()


@pytest.mark.django_db
def test_invoice_payment_failed_marks_past_due(user, plan_limits):
    sub = get_or_create_subscription(user)
    attach_stripe_customer(user, "cus_inv_fail")
    dispatch({
        "id": "evt_6",
        "type": "invoice.payment_failed",
        "data": {"object": {
            "customer": "cus_inv_fail",
            "amount_due": 9900,
            "attempt_count": 2,
        }},
    })
    sub.refresh_from_db()
    assert sub.status == "past_due"
