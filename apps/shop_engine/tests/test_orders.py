"""Order state-machine + refund tests."""
from __future__ import annotations

import pytest

from shop_engine.exceptions import (
    InvalidOrderTransition,
    RefundFailed,
)
from shop_engine.models import Order
from shop_engine.services import orders as orders_svc


def _new_order(user, **overrides):
    defaults = {
        "user": user,
        "email": user.email,
        "status": Order.STATUS_AWAITING_PAYMENT,
        "subtotal_cents": 10000,
        "total_cents": 10000,
        "stripe_payment_intent_id": "pi_test_xxx",
    }
    defaults.update(overrides)
    return Order.objects.create(**defaults)


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_transition_awaiting_to_paid_stamps_paid_at(user):
    order = _new_order(user)
    orders_svc.transition_order(order, new_status=Order.STATUS_PAID)
    assert order.status == Order.STATUS_PAID
    assert order.paid_at is not None


@pytest.mark.django_db
def test_transition_paid_to_fulfilling(user):
    order = _new_order(user, status=Order.STATUS_PAID)
    orders_svc.transition_order(order, new_status=Order.STATUS_FULFILLING)
    assert order.status == Order.STATUS_FULFILLING


@pytest.mark.django_db
def test_transition_invalid_raises(user):
    order = _new_order(user, status=Order.STATUS_AWAITING_PAYMENT)
    with pytest.raises(InvalidOrderTransition):
        orders_svc.transition_order(order, new_status=Order.STATUS_DELIVERED)


@pytest.mark.django_db
def test_transition_no_op_same_status(user):
    order = _new_order(user)
    paid_at_before = order.paid_at
    orders_svc.transition_order(order, new_status=Order.STATUS_AWAITING_PAYMENT)
    assert order.paid_at == paid_at_before


@pytest.mark.django_db
def test_transition_from_terminal_raises(user):
    order = _new_order(user, status=Order.STATUS_REFUNDED)
    with pytest.raises(InvalidOrderTransition):
        orders_svc.transition_order(order, new_status=Order.STATUS_PAID)


# ---------------------------------------------------------------------------
# Refunds
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_refund_full_flips_status(stub_stripe, user):
    order = _new_order(user, status=Order.STATUS_PAID, stripe_charge_id="ch_abc")
    orders_svc.refund_order(order)
    order.refresh_from_db()
    assert order.status == Order.STATUS_REFUNDED
    assert order.refunded_at is not None
    stub_stripe.Refund.create.assert_called_once()


@pytest.mark.django_db
def test_refund_partial_keeps_status(stub_stripe, user):
    order = _new_order(user, status=Order.STATUS_PAID, stripe_charge_id="ch_abc")
    orders_svc.refund_order(order, amount_cents=1000)
    order.refresh_from_db()
    assert order.status == Order.STATUS_PAID
    assert order.provider_metadata["refunded_cents_total"] == 1000


@pytest.mark.django_db
def test_refund_no_charge_raises(user):
    order = _new_order(user, status=Order.STATUS_PAID, stripe_payment_intent_id="", stripe_charge_id="")
    with pytest.raises(RefundFailed):
        orders_svc.refund_order(order)


@pytest.mark.django_db
def test_refund_unpaid_order_raises(user):
    order = _new_order(user, status=Order.STATUS_AWAITING_PAYMENT, stripe_charge_id="ch_x")
    with pytest.raises(RefundFailed):
        orders_svc.refund_order(order)
