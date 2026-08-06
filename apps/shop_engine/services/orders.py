"""Order state-machine + refund flow.

Allowed transitions
-------------------

    draft ──────► awaiting_payment ──► paid ──► fulfilling ──► shipped ──► delivered
       │                  │              │           │            │
       └──► cancelled     └──► failed    └──► refunded            └──► refunded
                                          │
                                          └──► cancelled

Anything not in this graph raises ``InvalidOrderTransition``. The
service is the single source of truth — admin actions, webhook
handlers, and management commands all go through it.

Refunds
-------
``refund_order`` calls Stripe's Refund API for the linked charge. If
``amount_cents`` is None, refunds the full ``total_cents``. Partial
refunds set ``status`` to ``refunded`` only when the cumulative refunded
amount equals the order total — otherwise the order keeps its previous
status and the refund is recorded on ``provider_metadata`` for the
audit trail.
"""
from __future__ import annotations

import logging
from typing import Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from ..exceptions import (
    InvalidOrderTransition,
    RefundFailed,
    StripeNotConfigured,
)
from ..models import AffiliateConversion, Order

logger = logging.getLogger(__name__)


# Valid transitions — origin -> set of allowed destinations.
_TRANSITIONS: dict[str, set[str]] = {
    Order.STATUS_DRAFT: {
        Order.STATUS_AWAITING_PAYMENT,
        Order.STATUS_CANCELLED,
    },
    Order.STATUS_AWAITING_PAYMENT: {
        Order.STATUS_PAID,
        Order.STATUS_FAILED,
        Order.STATUS_CANCELLED,
    },
    Order.STATUS_PAID: {
        Order.STATUS_FULFILLING,
        Order.STATUS_REFUNDED,
        Order.STATUS_CANCELLED,
    },
    Order.STATUS_FULFILLING: {
        Order.STATUS_SHIPPED,
        Order.STATUS_REFUNDED,
        Order.STATUS_CANCELLED,
    },
    Order.STATUS_SHIPPED: {
        Order.STATUS_DELIVERED,
        Order.STATUS_REFUNDED,
    },
    Order.STATUS_DELIVERED: {
        Order.STATUS_REFUNDED,
    },
    Order.STATUS_REFUNDED: set(),
    Order.STATUS_CANCELLED: set(),
    Order.STATUS_FAILED: set(),
}


_STATUS_TIMESTAMP_FIELD: dict[str, str] = {
    Order.STATUS_PAID: "paid_at",
    Order.STATUS_FULFILLING: "fulfilled_at",
    Order.STATUS_SHIPPED: "shipped_at",
    Order.STATUS_DELIVERED: "delivered_at",
    Order.STATUS_CANCELLED: "cancelled_at",
    Order.STATUS_REFUNDED: "refunded_at",
}


@transaction.atomic
def transition_order(order: Order, *, new_status: str) -> Order:
    """Move ``order`` to ``new_status``, validating the transition.

    Raises ``InvalidOrderTransition`` if the move isn't allowed.
    Auto-stamps the matching timestamp column (paid_at, shipped_at, ...).
    """
    if new_status == order.status:
        return order  # no-op
    allowed = _TRANSITIONS.get(order.status, set())
    if new_status not in allowed:
        raise InvalidOrderTransition(
            f"Cannot transition order {order.order_number} from {order.status} → {new_status}. "
            f"Allowed: {sorted(allowed) or '∅'}"
        )

    order.status = new_status
    update_fields = ["status", "updated_at"]
    ts_field = _STATUS_TIMESTAMP_FIELD.get(new_status)
    if ts_field and getattr(order, ts_field) is None:
        setattr(order, ts_field, timezone.now())
        update_fields.append(ts_field)
    order.save(update_fields=update_fields)
    logger.info("transition_order order=%s → %s", order.order_number, new_status)
    return order


# ---------------------------------------------------------------------------
# Refunds
# ---------------------------------------------------------------------------
def _stripe_module():
    if not getattr(settings, "STRIPE_SECRET_KEY", None):
        raise StripeNotConfigured("STRIPE_SECRET_KEY is not set.")
    try:
        import stripe  # type: ignore
    except ImportError as exc:
        raise StripeNotConfigured("The ``stripe`` SDK is not installed.") from exc
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


@transaction.atomic
def refund_order(order: Order, *, amount_cents: Optional[int] = None, reason: str = "") -> Order:
    """Issue a Stripe refund + flip status to ``refunded`` on a full refund.

    Raises ``RefundFailed`` if Stripe rejects, or if the order has no
    charge to refund. Partial refunds are tolerated — the order's
    status doesn't change until cumulative refunds equal the total.
    """
    if not order.stripe_payment_intent_id and not order.stripe_charge_id:
        raise RefundFailed(f"Order {order.order_number} has no Stripe charge to refund.")

    if order.status not in Order.PAID_STATUSES:
        raise RefundFailed(
            f"Order {order.order_number} status {order.status} cannot be refunded."
        )

    target_cents = int(amount_cents) if amount_cents is not None else int(order.total_cents)
    if target_cents <= 0:
        raise RefundFailed("Refund amount must be positive.")

    stripe = _stripe_module()
    payload = {"amount": target_cents}
    if order.stripe_charge_id:
        payload["charge"] = order.stripe_charge_id
    else:
        payload["payment_intent"] = order.stripe_payment_intent_id
    if reason:
        # Stripe accepts: duplicate, fraudulent, requested_by_customer.
        if reason in {"duplicate", "fraudulent", "requested_by_customer"}:
            payload["reason"] = reason

    try:
        refund = stripe.Refund.create(**payload)
    except Exception as exc:
        logger.exception("Stripe refund failed for order %s", order.order_number)
        raise RefundFailed(f"Stripe refund failed: {exc}") from exc

    # Record the refund in provider_metadata for audit.
    meta = order.provider_metadata or {}
    refunds_log = list(meta.get("refunds", []))
    refunds_log.append({
        "amount_cents": target_cents,
        "stripe_refund_id": getattr(refund, "id", "") or refund.get("id", ""),
        "reason": reason,
        "at": timezone.now().isoformat(),
    })
    meta["refunds"] = refunds_log
    meta["refunded_cents_total"] = sum(int(r["amount_cents"]) for r in refunds_log)
    order.provider_metadata = meta
    order.save(update_fields=["provider_metadata", "updated_at"])

    # If we hit the full total, flip status (within allowed transitions).
    if meta["refunded_cents_total"] >= int(order.total_cents) and not order.is_terminal:
        transition_order(order, new_status=Order.STATUS_REFUNDED)
        # Reverse affiliate conversion (if any) so the affiliate doesn't get paid for a refunded order.
        _reverse_affiliate_conversion(order)

    logger.info(
        "refund_order order=%s amount=%d total_refunded=%d",
        order.order_number, target_cents, meta["refunded_cents_total"],
    )
    return order


def _mark_refunded_from_webhook(order: Order) -> Order:
    """Webhook entry point — Stripe ``charge.refunded`` arrived.

    The refund row was created either by ``refund_order`` (our own
    code) or by an operator hitting Stripe's dashboard. We refresh
    ``provider_metadata.refunded_cents_total`` from Stripe and flip
    status if it covers the full total.
    """
    try:
        stripe = _stripe_module()
        charges = stripe.Charge.list(
            payment_intent=order.stripe_payment_intent_id, limit=1,
        )
        charge = charges.get("data", [{}])[0] if isinstance(charges, dict) else getattr(charges, "data", [{}])[0]
        refunded = int(charge.get("amount_refunded", 0)) if isinstance(charge, dict) else int(getattr(charge, "amount_refunded", 0))
    except Exception:
        logger.exception("Could not refresh refund total for order %s", order.order_number)
        refunded = int(order.total_cents)  # best effort — assume full refund

    meta = order.provider_metadata or {}
    meta["refunded_cents_total"] = refunded
    order.provider_metadata = meta
    update_fields = ["provider_metadata", "updated_at"]
    order.save(update_fields=update_fields)

    if refunded >= int(order.total_cents) and not order.is_terminal:
        transition_order(order, new_status=Order.STATUS_REFUNDED)
        _reverse_affiliate_conversion(order)
    return order


def _reverse_affiliate_conversion(order: Order) -> None:
    """Mark the order's affiliate conversion (if any) as ``reversed``.

    Called on full refund so the affiliate doesn't get paid for a sale
    that was rolled back. The conversion isn't deleted — operators
    sometimes want to see the history "this order was attributed and
    then reversed because of a refund".
    """
    conv = AffiliateConversion.objects.filter(order=order).first()
    if conv is None:
        return
    if conv.status == AffiliateConversion.STATUS_PAID:
        logger.warning(
            "Affiliate conversion %s on refunded order %s was already PAID; "
            "leaving it marked PAID but logging a reversal warning. "
            "Manual clawback may be required.",
            conv.pk, order.order_number,
        )
        return
    conv.status = AffiliateConversion.STATUS_REVERSED
    conv.save(update_fields=["status"])
    logger.info("Affiliate conversion %s reversed (order refunded).", conv.pk)
