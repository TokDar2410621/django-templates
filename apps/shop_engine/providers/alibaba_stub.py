"""Alibaba (1688/Alibaba.com) catalogue provider — STUB.

This module is an EXTENSION EXAMPLE, not a working integration. Each
method raises ``NotImplementedError`` with a docstring documenting the
shape it would have to return. Use it as a template when wiring a real
Alibaba integration (or any other dropship marketplace).

What you'll need from Alibaba:

- An app credential pair (``app_key`` + ``app_secret``).
- A token-exchange flow (most marketplaces require an OAuth-style dance
  before you can hit catalogue endpoints).
- A grasp of Alibaba's category taxonomy (their numeric category IDs
  don't map cleanly to user-facing slugs).

The integration cost is non-trivial — count on a sprint to get the
catalogue sync right, plus continuous maintenance because the upstream
API changes more often than you'd like.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from django.conf import settings

from ..exceptions import ProviderNotConfigured
from .base import (
    CatalogProvider,
    ProductData,
    ProductListResult,
    SyncResult,
)

logger = logging.getLogger(__name__)


class AlibabaCatalogProvider(CatalogProvider):
    """STUB — replace each method body with a real Alibaba API call.

    The class boots and accepts kwargs so a project can swap it in via
    settings without immediately crashing. The methods all raise
    ``NotImplementedError`` so you can't accidentally run a half-wired
    integration in production — you'd notice on the first sync attempt.
    """

    name = "alibaba"

    def __init__(self, **_: Any) -> None:
        # Load creds from settings. We DON'T raise here — that would
        # crash apps that have this class in their setting but no key,
        # which is fine in dev. We raise on first method call instead.
        self.app_key = getattr(settings, "ALIBABA_APP_KEY", "")
        self.app_secret = getattr(settings, "ALIBABA_APP_SECRET", "")
        self.access_token = getattr(settings, "ALIBABA_ACCESS_TOKEN", "")

    def _require_credentials(self) -> None:
        if not (self.app_key and self.app_secret and self.access_token):
            raise ProviderNotConfigured(
                "Alibaba provider requires ALIBABA_APP_KEY + ALIBABA_APP_SECRET "
                "+ ALIBABA_ACCESS_TOKEN in settings."
            )

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------
    def list_products(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        **filters: Any,
    ) -> ProductListResult:
        """List products from Alibaba's catalogue.

        Example wire shape (1688 product list endpoint):

            POST https://gw.open.1688.com/openapi/...
            payload: {
                "access_token": "<token>",
                "page": 1,
                "pageSize": 50,
                "keyword": "hoodie",  # if filters['q']
                "categoryId": 1234,    # if filters['category_id']
            }
            response: {
                "data": {
                    "products": [
                        {
                            "productId": "608123...",
                            "subject": "Hoodie 100% coton...",
                            "priceInfo": {"price": "15.50", ...},
                            "skuList": [...],
                            "imageList": [...],
                            ...
                        },
                    ],
                    "totalCount": 1234,
                }
            }

        You map each ``data.products[i]`` to a ``ProductData`` instance
        — see the docstring on the dataclass in ``base.py``.
        """
        self._require_credentials()
        raise NotImplementedError(
            "AlibabaCatalogProvider.list_products is a stub. "
            "Wire in the real 1688/Alibaba list-products call. "
            "See this method's docstring for the expected shape."
        )

    def get_product(self, external_id: str) -> Optional[ProductData]:
        """Fetch a single product by its Alibaba product ID.

        Expected endpoint: ``alibaba.product.detail.get`` with
        ``productId=<external_id>``. Return ``None`` on a 404-style
        response; raise on auth/network errors.
        """
        self._require_credentials()
        raise NotImplementedError(
            "AlibabaCatalogProvider.get_product is a stub. "
            "See this method's docstring for the expected wiring."
        )

    def check_availability(self, sku: str, qty: int) -> bool:
        """Live availability check.

        Alibaba's quantity calls are SKU-scoped — pass the SKU and the
        endpoint returns the in-stock count. Cache aggressively (a
        few minutes) because Alibaba rate-limits availability calls.
        """
        self._require_credentials()
        raise NotImplementedError(
            "AlibabaCatalogProvider.check_availability is a stub."
        )

    # ------------------------------------------------------------------
    # Sync workflow
    # ------------------------------------------------------------------
    def sync_to_local(self, *, force: bool = False) -> SyncResult:
        """Walk the Alibaba catalogue and UPSERT into our ``Product`` rows.

        Recommended loop::

            page = 1
            while True:
                page_result = self.list_products(page=page, page_size=100)
                for prod in page_result.products:
                    catalog_service.upsert_from_provider_data(
                        provider=self.name, data=prod,
                    )
                if page_result.next_page is None:
                    break
                page = page_result.next_page

        The ``upsert_from_provider_data`` service handles the
        Product / ProductVariant / Tag / Category creation;
        ``sync_to_local`` only owns the iteration + error handling +
        ``ProviderSyncLog`` writes.
        """
        self._require_credentials()
        raise NotImplementedError(
            "AlibabaCatalogProvider.sync_to_local is a stub. "
            "See the docstring for the recommended pagination loop."
        )
