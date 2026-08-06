"""Fulfillment — dispatch paid orders to the configured provider.

Two flavours:

- **Local provider** (manual ops). ``dispatch_to_provider`` flips the
  order to ``fulfilling`` and writes a ProviderSyncLog row; the operator
  ships from the admin and calls ``mark_shipped`` / ``mark_delivered``
  manually.
- **External provider** (Gelato/Alibaba/etc.). ``dispatch_to_provider``
  calls ``provider.create_order``, stores the upstream order ID in
  ``Order.provider_metadata``, flips status to ``fulfilling``.
  Periodic Celery task ``poll_provider_order_status`` then polls the
  provider for status changes and calls ``mark_shipped`` /
  ``mark_delivered`` automatically.

Idempotency: ``dispatch_to_provider`` checks whether the order already
has a ``provider_metadata["external_order_id"]`` set and skips the
upstream call if so — safe to retry on transient failures.
"""
from __future__ import annotations

import logging

from django.db import transaction

from ..models import Order, ProviderSyncLog
from ..providers import get_fulfillment_provider
from . import orders as orders_svc

logger = logging.getLogger(__name__)


@transaction.atomic
def dispatch_to_provider(order: Order) -> Order:
    """Send the order to the upstream provider, transition to ``fulfilling``.

    Safe to call multiple times — re-dispatches only if no
    ``external_order_id`` is recorded yet.
    """
    if order.status != Order.STATUS_PAID:
        # Not paid yet — nothing to dispatch. Don't raise; the periodic
        # task calls this on every paid order and we don't want spam.
        return order

    meta = order.provider_metadata or {}
    if meta.get("external_order_id"):
        # Already dispatched — just flip status if it hadn't been moved yet.
        if order.status == Order.STATUS_PAID:
            orders_svc.transition_order(order, new_status=Order.STATUS_FULFILLING)
        return order

    provider = get_fulfillment_provider()
    try:
        result = provider.create_order(order)
    except Exception as exc:
        logger.exception("Provider dispatch failed for order %s", order.order_number)
        ProviderSyncLog.objects.create(
            provider=provider.name,
            action="create_order",
            external_id=order.order_number,
            payload={},
            status=ProviderSyncLog.STATUS_ERROR,
            error_message=str(exc),
        )
        raise

    meta["external_order_id"] = result.external_order_id
    meta["provider"] = provider.name
    meta["provider_status"] = result.status
    order.provider_metadata = meta
    order.save(update_fields=["provider_metadata", "updated_at"])

    orders_svc.transition_order(order, new_status=Order.STATUS_FULFILLING)
    logger.info(
        "dispatch_to_provider order=%s → %s (external=%s)",
        order.order_number, provider.name, result.external_order_id,
    )
    return order


@transaction.atomic
def mark_shipped(order: Order, *, tracking_number: str = "", tracking_url: str = "", carrier: str = "") -> Order:
    """Record tracking info + transition the order to ``shipped``."""
    meta = order.provider_metadata or {}
    if tracking_number:
        meta["tracking_number"] = tracking_number
    if tracking_url:
        meta["tracking_url"] = tracking_url
    if carrier:
        meta["carrier"] = carrier
    order.provider_metadata = meta
    order.save(update_fields=["provider_metadata", "updated_at"])
    return orders_svc.transition_order(order, new_status=Order.STATUS_SHIPPED)


def mark_delivered(order: Order) -> Order:
    """Transition the order to ``delivered``."""
    return orders_svc.transition_order(order, new_status=Order.STATUS_DELIVERED)
