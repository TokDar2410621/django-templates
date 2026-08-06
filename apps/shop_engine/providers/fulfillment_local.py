"""Local (manual) fulfillment provider — operator marks orders shipped from admin.

This is the default — assumes you're physically fulfilling orders
yourself, or that another system you control picks orders out of the DB
and tracks them manually. ``create_order`` writes a sync log row and
returns immediately; ``get_order_status`` and friends just read what's
on the Order model.

If you want to integrate a real POD / dropship provider, copy
``gelato_stub.py`` instead and implement the methods.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from ..models import Order, ProviderSyncLog
from .base import (
    FulfillmentProvider,
    ProviderOrderResult,
    ProviderOrderStatus,
    TrackingInfo,
)

logger = logging.getLogger(__name__)


class LocalFulfillmentProvider(FulfillmentProvider):
    """No-op fulfillment — manual ops via the admin."""

    name = "local"

    def __init__(self, **_: Any) -> None:
        pass

    def create_order(self, order: Order) -> ProviderOrderResult:
        """Record the dispatch in the sync log and return.

        We don't transition the Order's status here — the caller
        (``services.fulfillment.dispatch_to_provider``) is responsible
        for that. We just leave a breadcrumb so operators can audit
        "when was this order considered dispatched?".
        """
        logger.info("LocalFulfillmentProvider.create_order — order=%s (manual)", order.order_number)
        ProviderSyncLog.objects.create(
            provider=self.name,
            action="create_order",
            external_id=order.order_number,
            payload={"order_number": order.order_number, "status": order.status},
            status=ProviderSyncLog.STATUS_OK,
        )
        return ProviderOrderResult(
            external_order_id=order.order_number,
            status="awaiting_manual_fulfillment",
            raw_response={"detail": "Manual fulfillment — operator will ship from admin."},
        )

    def get_order_status(self, external_order_id: str) -> ProviderOrderStatus:
        """Return the local Order's status verbatim."""
        order = Order.objects.filter(order_number=external_order_id).first()
        status = order.status if order else "unknown"
        return ProviderOrderStatus(
            external_order_id=external_order_id,
            status=status,
            raw_response={},
        )

    def cancel_order(self, external_order_id: str) -> bool:
        """No upstream to cancel — succeeds silently. The local Order's
        status is updated by the cancellation service, not here.
        """
        ProviderSyncLog.objects.create(
            provider=self.name,
            action="cancel_order",
            external_id=external_order_id,
            payload={},
            status=ProviderSyncLog.STATUS_OK,
        )
        return True

    def get_tracking(self, external_order_id: str) -> Optional[TrackingInfo]:
        """Return whatever the operator typed into the Order's provider_metadata.

        Expected keys: ``{"carrier": ..., "tracking_number": ...,
        "tracking_url": ...}``. Returns None if no tracking has been set.
        """
        order = Order.objects.filter(order_number=external_order_id).first()
        if order is None:
            return None
        meta = order.provider_metadata or {}
        tracking_number = (meta.get("tracking_number") or "").strip()
        if not tracking_number:
            return None
        return TrackingInfo(
            external_order_id=external_order_id,
            carrier=meta.get("carrier") or "unknown",
            tracking_number=tracking_number,
            tracking_url=meta.get("tracking_url") or None,
            raw_response=meta,
        )
