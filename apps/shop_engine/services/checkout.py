"""Checkout services — turn a Cart into an Order + a Stripe PaymentIntent.

Flow
----
1. ``create_checkout(cart, billing, shipping, customer_email)`` — server-side:
   - Re-validate the cart (live prices, stock).
   - Snapshot every line into an ``OrderItem``.
   - Compute totals via ``services.cart.calculate_totals``.
   - Insert a ``CouponUsage`` row + atomic increment ``Coupon.times_used``.
   - Create a Stripe ``PaymentIntent`` with ``amount=total_cents``,
     ``metadata={order_number, order_id}``.
   - Persist ``Order.stripe_payment_intent_id``.
   - Return ``(order, client_secret)`` so the FE can confirm via Stripe.js.
2. The customer confirms the PaymentIntent on the FE.
3. Stripe sends a webhook → ``services.checkout.confirm_payment`` flips
   the Order to ``paid`` + clears the cart.

Idempotency
-----------
``Order.order_number`` is unique. ``Cart`` → ``Order`` is one-shot per
cart; a second checkout call on a cart that already has an open
``awaiting_payment`` order returns the existing order (so a frontend
retry never double-creates).
"""
from __future__ import annotations

import logging
from typing import Optional

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from ..exceptions import (
    CartEmpty,
    CheckoutGuestEmailRequired,
    InvalidOrderTransition,
    StripeNotConfigured,
    WebhookSignatureInvalid,
)
from ..models import Cart, CartItem, Coupon, CouponUsage, Order, OrderItem
from . import affiliates as affiliates_svc
from . import cart as cart_svc

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stripe lazy import
# ---------------------------------------------------------------------------
def _stripe_module():
    """Lazy import — raises ``StripeNotConfigured`` if the SDK or secret is missing.

    Allows the rest of the engine (cart math, admin, tests of unrelated
    code) to run without the ``stripe`` package installed.
    """
    if not getattr(settings, "STRIPE_SECRET_KEY", None):
        raise StripeNotConfigured(
            "STRIPE_SECRET_KEY is not set. Checkout cannot create PaymentIntents."
        )
    try:
        import stripe  # type: ignore
    except ImportError as exc:
        raise StripeNotConfigured(
            "The ``stripe`` SDK is not installed. Run `pip install stripe`."
        ) from exc
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


# ---------------------------------------------------------------------------
# Create checkout
# ---------------------------------------------------------------------------
@transaction.atomic
def create_checkout(
    cart: Cart,
    *,
    billing_address: dict,
    shipping_address: dict,
    customer_email: str = "",
    customer_notes: str = "",
) -> tuple[Order, str]:
    """Convert ``cart`` to an Order + return ``(order, stripe_client_secret)``.

    The cart is **not deleted** at checkout — it's deleted by
    ``confirm_payment`` when Stripe confirms the charge. That way, if
    the customer abandons the Stripe page, they come back to the cart
    intact.
    """
    items = list(cart.items.select_related("product", "variant"))
    if not items:
        raise CartEmpty("Cart is empty — cannot create order.")

    user = cart.user
    if user is None:
        # Guest checkout — email is required.
        if not getattr(settings, "SHOP_GUEST_CHECKOUT_ENABLED", True):
            raise CheckoutGuestEmailRequired(
                "Guest checkout is disabled. Please log in to place an order."
            )
        if not customer_email:
            raise CheckoutGuestEmailRequired("Guest checkout requires an email address.")
    else:
        # Authenticated — fall back to the user's email when none provided.
        customer_email = customer_email or getattr(user, "email", "") or ""
        if not customer_email:
            raise CheckoutGuestEmailRequired("Customer email is required.")

    # Idempotency — if this cart already has an in-flight order, return it.
    existing = Order.objects.filter(
        user=user,
        status=Order.STATUS_AWAITING_PAYMENT,
        # We match by user+email+pending-status — not perfect for a user with
        # multiple parallel devices, but a sane default. Override the
        # service for stricter guarantees if needed.
        email=customer_email,
    ).order_by("-created_at").first()
    if existing and existing.stripe_payment_intent_id:
        try:
            stripe = _stripe_module()
            pi = stripe.PaymentIntent.retrieve(existing.stripe_payment_intent_id)
            client_secret = getattr(pi, "client_secret", "") or pi.get("client_secret", "")
            if client_secret:
                logger.info("create_checkout returning existing order %s", existing.order_number)
                return existing, client_secret
        except Exception:
            logger.warning("Could not retrieve PI for existing order %s; creating fresh.", existing.order_number)

    totals = cart_svc.calculate_totals(cart)

    order = Order.objects.create(
        user=user,
        email=customer_email,
        status=Order.STATUS_AWAITING_PAYMENT,
        billing_address=billing_address or {},
        shipping_address=shipping_address or billing_address or {},
        subtotal_cents=totals["subtotal_cents"],
        shipping_cents=totals["shipping_cents"],
        tax_cents=totals["tax_cents"],
        discount_cents=totals["discount_cents"],
        total_cents=totals["total_cents"],
        currency=cart.currency,
        applied_coupon_code=cart.applied_coupon.code if cart.applied_coupon_id else "",
        affiliate_code=cart.affiliate_code,
        customer_notes=customer_notes or "",
        placed_at=timezone.now(),
    )

    for item in items:
        OrderItem.objects.create(
            order=order,
            product=item.product,
            variant=item.variant,
            product_title=item.product.title,
            variant_label=item.variant.label if item.variant else "",
            sku=item.variant.sku if item.variant else "",
            unit_price_cents=item.unit_price_cents,
            quantity=item.quantity,
            line_total_cents=item.line_total_cents,
        )

    # Coupon usage (idempotent on (coupon, order) — at create time there
    # is at most one usage; we still let the DB enforce it).
    if cart.applied_coupon_id:
        CouponUsage.objects.get_or_create(
            coupon=cart.applied_coupon,
            order=order,
            defaults={"user": user},
        )
        Coupon.objects.filter(pk=cart.applied_coupon_id).update(
            times_used=F("times_used") + 1,
        )

    # Stripe PaymentIntent
    stripe = _stripe_module()
    try:
        intent = stripe.PaymentIntent.create(
            amount=order.total_cents,
            currency=order.currency.lower(),
            metadata={
                "order_number": order.order_number,
                "order_id": str(order.pk),
            },
            receipt_email=order.email,
            description=f"Order {order.order_number}",
        )
    except Exception:
        logger.exception("Stripe PI create failed for order %s", order.order_number)
        # Roll back the transaction — the @transaction.atomic decorator
        # handles it as soon as we re-raise.
        raise

    order.stripe_payment_intent_id = getattr(intent, "id", "") or intent.get("id", "")
    order.save(update_fields=["stripe_payment_intent_id"])

    client_secret = getattr(intent, "client_secret", "") or intent.get("client_secret", "")
    logger.info(
        "create_checkout order=%s total=%d %s pi=%s",
        order.order_number, order.total_cents, order.currency, order.stripe_payment_intent_id,
    )
    return order, client_secret


# ---------------------------------------------------------------------------
# Webhook entry points
# ---------------------------------------------------------------------------
@transaction.atomic
def confirm_payment(order: Order, *, stripe_charge_id: str = "") -> Order:
    """Mark an order paid + clear the originating cart.

    Idempotent — re-calling on an already-paid order is a no-op. Used
    by ``payment_intent.succeeded`` and ``charge.succeeded`` webhooks
    interchangeably.
    """
    if order.status == Order.STATUS_PAID or order.is_paid:
        return order
    if order.status != Order.STATUS_AWAITING_PAYMENT:
        # Allow draft → paid too (edge case: admin marks paid manually).
        if order.status != Order.STATUS_DRAFT:
            raise InvalidOrderTransition(
                f"Order {order.order_number} is {order.status}, cannot mark paid."
            )

    order.status = Order.STATUS_PAID
    order.paid_at = timezone.now()
    if stripe_charge_id:
        order.stripe_charge_id = stripe_charge_id
    order.save(update_fields=["status", "paid_at", "stripe_charge_id", "updated_at"])

    # Clear the user's cart now that payment is locked in.
    Cart.objects.filter(user=order.user).update(applied_coupon=None)
    CartItem.objects.filter(cart__user=order.user).delete()

    # Affiliate attribution — best effort. If the cart had an affiliate
    # code, register a conversion for it.
    if order.affiliate_code:
        try:
            affiliates_svc.attribute_conversion(order=order, code=order.affiliate_code)
        except Exception:
            logger.exception(
                "Affiliate attribution failed for order %s (code=%s)",
                order.order_number, order.affiliate_code,
            )

    logger.info("confirm_payment order=%s charge=%s", order.order_number, stripe_charge_id)
    return order


@transaction.atomic
def mark_failed(order: Order, *, reason: str = "") -> Order:
    """Mark an order as ``failed`` (Stripe ``payment_intent.payment_failed``)."""
    if order.is_terminal:
        return order
    order.status = Order.STATUS_FAILED
    order.save(update_fields=["status", "updated_at"])
    logger.info("mark_failed order=%s reason=%s", order.order_number, reason)
    return order


# ---------------------------------------------------------------------------
# Webhook dispatcher
# ---------------------------------------------------------------------------
def process_stripe_webhook(*, payload: bytes, signature_header: str) -> Optional[Order]:
    """Verify + dispatch a Stripe webhook to the right service.

    Caller (the view) just hands us ``request.body`` + the signature
    header; we do everything else. Returns the affected ``Order`` or
    ``None`` for unhandled event types.
    """
    secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", "")
    if not secret:
        raise StripeNotConfigured("STRIPE_WEBHOOK_SECRET is not set.")

    stripe = _stripe_module()
    try:
        event = stripe.Webhook.construct_event(payload, signature_header, secret)
    except Exception as exc:
        raise WebhookSignatureInvalid(f"Invalid Stripe signature: {exc}") from exc

    event_type = event.get("type") if isinstance(event, dict) else event.type
    data_object = (event.get("data", {}) if isinstance(event, dict) else event["data"]).get("object", {})

    if event_type == "payment_intent.succeeded":
        pi_id = data_object.get("id", "")
        charge_id = (data_object.get("latest_charge") or "") if isinstance(data_object, dict) else ""
        order = Order.objects.filter(stripe_payment_intent_id=pi_id).first()
        if order is None:
            logger.warning("Stripe webhook PI %s with no matching order.", pi_id)
            return None
        return confirm_payment(order, stripe_charge_id=charge_id)

    if event_type == "payment_intent.payment_failed":
        pi_id = data_object.get("id", "")
        order = Order.objects.filter(stripe_payment_intent_id=pi_id).first()
        if order is None:
            return None
        reason = ""
        if isinstance(data_object, dict):
            reason = ((data_object.get("last_payment_error") or {}).get("message") or "")
        return mark_failed(order, reason=reason)

    if event_type == "charge.refunded":
        pi_id = data_object.get("payment_intent", "") if isinstance(data_object, dict) else ""
        order = Order.objects.filter(stripe_payment_intent_id=pi_id).first()
        if order is None:
            return None
        from . import orders as orders_svc  # local import — avoid cycle
        return orders_svc._mark_refunded_from_webhook(order)

    logger.info("Stripe webhook event %s — no handler, skipping.", event_type)
    return None
