"""Stripe webhook dispatch tests."""
from __future__ import annotations

import pytest

from shop_engine.exceptions import WebhookSignatureInvalid
from shop_engine.models import Order
from shop_engine.services import cart as cart_svc
from shop_engine.services import checkout as checkout_svc


BILLING = {"name": "A", "line1": "1", "city": "X", "postal_code": "1A1A1A", "country": "CA"}


def _make_order(user_cart, product, variant):
    cart_svc.add_to_cart(user_cart, product=product, variant=variant, quantity=1)
    order, _ = checkout_svc.create_checkout(
        user_cart, billing_address=BILLING, shipping_address=BILLING,
        customer_email=user_cart.user.email,
    )
    return order


@pytest.mark.django_db
def test_webhook_payment_intent_succeeded_marks_paid(stub_stripe, user_cart, product, variant):
    order = _make_order(user_cart, product, variant)

    stub_stripe.Webhook.construct_event.return_value = {
        "type": "payment_intent.succeeded",
        "data": {"object": {"id": order.stripe_payment_intent_id, "latest_charge": "ch_succ"}},
    }
    result = checkout_svc.process_stripe_webhook(payload=b"{}", signature_header="sig_x")
    assert result.status == Order.STATUS_PAID


@pytest.mark.django_db
def test_webhook_payment_failed_marks_failed(stub_stripe, user_cart, product, variant):
    order = _make_order(user_cart, product, variant)

    stub_stripe.Webhook.construct_event.return_value = {
        "type": "payment_intent.payment_failed",
        "data": {"object": {
            "id": order.stripe_payment_intent_id,
            "last_payment_error": {"message": "Card declined."},
        }},
    }
    result = checkout_svc.process_stripe_webhook(payload=b"{}", signature_header="sig_x")
    assert result.status == Order.STATUS_FAILED


@pytest.mark.django_db
def test_webhook_unknown_event_is_skipped(stub_stripe, user_cart, product, variant):
    _make_order(user_cart, product, variant)
    stub_stripe.Webhook.construct_event.return_value = {
        "type": "customer.created",
        "data": {"object": {}},
    }
    result = checkout_svc.process_stripe_webhook(payload=b"{}", signature_header="sig_x")
    assert result is None


@pytest.mark.django_db
def test_webhook_invalid_signature_raises(stub_stripe):
    stub_stripe.Webhook.construct_event.side_effect = Exception("Invalid sig")
    with pytest.raises(WebhookSignatureInvalid):
        checkout_svc.process_stripe_webhook(payload=b"{}", signature_header="bad_sig")
