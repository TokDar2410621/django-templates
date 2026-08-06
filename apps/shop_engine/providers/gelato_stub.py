"""Gelato print-on-demand fulfillment provider — STUB.

Same pattern as ``alibaba_stub.py`` — each method documents the wire
shape and raises ``NotImplementedError``. Replace bodies to ship a real
Gelato integration.

Gelato is the recommended POD provider for projects with print-on-demand
clothing + stickers (per the SendMenow lessons-learned). The docstrings
below match Gelato's v3 Order API as of writing — verify against the
current docs before flesh-out.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from django.conf import settings

from ..exceptions import ProviderNotConfigured
from ..models import Order
from .base import (
    FulfillmentProvider,
    ProviderOrderResult,
    ProviderOrderStatus,
    TrackingInfo,
)

logger = logging.getLogger(__name__)


class GelatoFulfillmentProvider(FulfillmentProvider):
    """STUB — replace each method body with a real Gelato API call."""

    name = "gelato"

    def __init__(self, **_: Any) -> None:
        self.api_key = getattr(settings, "GELATO_API_KEY", "")
        # ``base_url`` is configurable so projects can point at the
        # sandbox during dev. Production: https://order.gelatoapis.com
        self.base_url = getattr(
            settings, "GELATO_BASE_URL", "https://order.gelatoapis.com",
        )

    def _require_credentials(self) -> None:
        if not self.api_key:
            raise ProviderNotConfigured(
                "Gelato provider requires GELATO_API_KEY in settings."
            )

    # ------------------------------------------------------------------
    # Order dispatch
    # ------------------------------------------------------------------
    def create_order(self, order: Order) -> ProviderOrderResult:
        """Submit ``order`` to Gelato for printing + shipping.

        Wire shape (POST /v4/orders)::

            headers = {"X-API-KEY": "<api_key>"}
            payload = {
                "orderReferenceId": order.order_number,
                "customerReferenceId": str(order.user_id or order.email),
                "currency": order.currency,
                "items": [
                    {
                        "itemReferenceId": str(item.pk),
                        "productUid": <map item.sku → Gelato's product UID>,
                        "files": [{"type": "default", "url": "<print file URL>"}],
                        "quantity": item.quantity,
                    }
                    for item in order.items.all()
                ],
                "shippingAddress": {
                    "firstName": ..., "lastName": ...,
                    "addressLine1": ..., "city": ..., "postCode": ...,
                    "country": "CA",
                    "email": order.email,
                },
            }

        Response::

            { "id": "gel_ord_abc123", "orderStatus": "submitted", ... }

        Persist ``id`` into ``Order.provider_metadata["external_order_id"]``
        and let ``services.fulfillment.dispatch_to_provider`` transition
        ``Order.status`` to ``fulfilling`` after a successful call.
        """
        self._require_credentials()
        raise NotImplementedError(
            "GelatoFulfillmentProvider.create_order is a stub. "
            "See this method's docstring for the v4 Orders API payload shape."
        )

    def get_order_status(self, external_order_id: str) -> ProviderOrderStatus:
        """Poll Gelato for an order's current status.

        Endpoint: ``GET /v4/orders/<external_order_id>``. Maps to one of
        ``submitted``, ``processing``, ``printed``, ``shipped``,
        ``delivered``, ``cancelled``, ``failed``. Map those to our
        ``Order.STATUS_*`` values in the calling service.
        """
        self._require_credentials()
        raise NotImplementedError(
            "GelatoFulfillmentProvider.get_order_status is a stub."
        )

    def cancel_order(self, external_order_id: str) -> bool:
        """Cancel an order before Gelato starts printing.

        Endpoint: ``DELETE /v4/orders/<external_order_id>``. Returns
        True on 200, False on 4xx (already shipped, etc.). Raises on
        auth/network errors so the caller can retry.
        """
        self._require_credentials()
        raise NotImplementedError(
            "GelatoFulfillmentProvider.cancel_order is a stub."
        )

    def get_tracking(self, external_order_id: str) -> Optional[TrackingInfo]:
        """Pull the latest tracking info.

        Gelato exposes tracking via the same order GET endpoint
        (``shipments[].trackingCode`` + ``trackingUrl`` per shipment).
        Return ``None`` if the order has no shipped shipments yet.
        """
        self._require_credentials()
        raise NotImplementedError(
            "GelatoFulfillmentProvider.get_tracking is a stub."
        )
