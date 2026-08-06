"""Checkout service tests — create order, guest-required-email, Stripe PI."""
from __future__ import annotations

import pytest

from shop_engine.exceptions import CartEmpty, CheckoutGuestEmailRequired
from shop_engine.models import Cart, Order, OrderItem
from shop_engine.services import cart as cart_svc
from shop_engine.services import checkout as checkout_svc


BILLING = {
    "name": "Alice Smith",
    "line1": "123 Main",
    "city": "Montréal",
    "postal_code": "H1A 1A1",
    "country": "CA",
}


@pytest.mark.django_db
def test_create_checkout_happy_path(user_cart, product, variant, stub_stripe):
    cart_svc.add_to_cart(user_cart, product=product, variant=variant, quantity=2)
    order, client_secret = checkout_svc.create_checkout(
        user_cart,
        billing_address=BILLING,
        shipping_address=BILLING,
        customer_email=user_cart.user.email,
    )

    assert order.status == Order.STATUS_AWAITING_PAYMENT
    assert order.email == user_cart.user.email
    assert order.subtotal_cents == 2 * 4999
    assert order.items.count() == 1
    assert order.items.first().quantity == 2
    assert order.stripe_payment_intent_id == "pi_test_123"
    assert client_secret == "cs_test_abc"

    # PaymentIntent was created with the right amount.
    stub_stripe.PaymentIntent.create.assert_called_once()
    call_kwargs = stub_stripe.PaymentIntent.create.call_args.kwargs
    assert call_kwargs["amount"] == order.total_cents
    assert call_kwargs["metadata"]["order_number"] == order.order_number


@pytest.mark.django_db
def test_create_checkout_empty_cart_raises(user_cart):
    with pytest.raises(CartEmpty):
        checkout_svc.create_checkout(
            user_cart, billing_address=BILLING, shipping_address=BILLING,
            customer_email="x@x.com",
        )


@pytest.mark.django_db
def test_create_checkout_guest_requires_email(anon_cart, product, variant):
    cart_svc.add_to_cart(anon_cart, product=product, variant=variant, quantity=1)
    with pytest.raises(CheckoutGuestEmailRequired):
        checkout_svc.create_checkout(
            anon_cart, billing_address=BILLING, shipping_address=BILLING,
            customer_email="",
        )


@pytest.mark.django_db
def test_create_checkout_guest_happy_path(anon_cart, product, variant, stub_stripe):
    cart_svc.add_to_cart(anon_cart, product=product, variant=variant, quantity=1)
    order, client_secret = checkout_svc.create_checkout(
        anon_cart, billing_address=BILLING, shipping_address=BILLING,
        customer_email="guest@example.com",
    )
    assert order.user_id is None
    assert order.email == "guest@example.com"
    assert client_secret == "cs_test_abc"


@pytest.mark.django_db
def test_create_checkout_snapshots_coupon_and_affiliate(user_cart, product, variant, coupon_percent, stub_stripe):
    cart_svc.add_to_cart(user_cart, product=product, variant=variant, quantity=1)
    cart_svc.apply_coupon(user_cart, code="SAVE10")
    user_cart.affiliate_code = "REFXYZ"
    user_cart.save()

    order, _ = checkout_svc.create_checkout(
        user_cart, billing_address=BILLING, shipping_address=BILLING,
        customer_email=user_cart.user.email,
    )
    assert order.applied_coupon_code == "SAVE10"
    assert order.affiliate_code == "REFXYZ"
    coupon_percent.refresh_from_db()
    assert coupon_percent.times_used == 1


# ---------------------------------------------------------------------------
# confirm_payment
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_confirm_payment_marks_paid_and_clears_cart(user_cart, product, variant, stub_stripe):
    cart_svc.add_to_cart(user_cart, product=product, variant=variant, quantity=1)
    order, _ = checkout_svc.create_checkout(
        user_cart, billing_address=BILLING, shipping_address=BILLING,
        customer_email=user_cart.user.email,
    )
    checkout_svc.confirm_payment(order, stripe_charge_id="ch_abc")
    order.refresh_from_db()
    assert order.status == Order.STATUS_PAID
    assert order.paid_at is not None
    assert order.stripe_charge_id == "ch_abc"
    # Cart items are gone.
    assert user_cart.items.count() == 0


@pytest.mark.django_db
def test_confirm_payment_idempotent(user_cart, product, variant, stub_stripe):
    cart_svc.add_to_cart(user_cart, product=product, variant=variant, quantity=1)
    order, _ = checkout_svc.create_checkout(
        user_cart, billing_address=BILLING, shipping_address=BILLING,
        customer_email=user_cart.user.email,
    )
    checkout_svc.confirm_payment(order, stripe_charge_id="ch_abc")
    checkout_svc.confirm_payment(order, stripe_charge_id="ch_xyz")  # second call no-op
    order.refresh_from_db()
    assert order.status == Order.STATUS_PAID
