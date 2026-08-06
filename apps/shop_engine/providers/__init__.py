"""Provider abstraction — catalogue + fulfillment.

Two protocols (``CatalogProvider`` and ``FulfillmentProvider``) live in
``base.py`` and define the surface every provider implementation has to
fill. The ship-by-default implementations are:

- ``LocalCatalogProvider`` (``providers.local.LocalCatalogProvider``) —
  serves the catalogue out of the ``Product`` / ``ProductVariant``
  tables. The default; nothing else to configure.
- ``LocalFulfillmentProvider``
  (``providers.fulfillment_local.LocalFulfillmentProvider``) — manual
  fulfillment: ``create_order`` is a no-op (the operator marks orders
  shipped from the admin). The default for projects without an upstream
  POD provider.

Two STUB implementations show how to wire a real provider:

- ``AlibabaCatalogProvider`` (``providers.alibaba_stub``) — every method
  raises ``NotImplementedError`` with a docstring documenting the
  expected request/response shape. Replace the bodies with real HTTP
  calls.
- ``GelatoFulfillmentProvider`` (``providers.gelato_stub``) — same
  shape, focused on print-on-demand fulfillment.

To switch providers, set the dotted paths in ``settings.py``:

    SHOP_CATALOG_PROVIDER = "myproject.providers.MyCatalog"
    SHOP_FULFILLMENT_PROVIDER = "myproject.providers.MyFulfillment"

``get_catalog_provider()`` and ``get_fulfillment_provider()`` lazily
import the configured class so a typo doesn't crash the boot — it
crashes the FIRST CALL with a clear message.
"""
from __future__ import annotations

import importlib
import logging
from typing import Any

from django.conf import settings

from .base import (  # noqa: F401 — re-exports for convenience
    CatalogProvider,
    FulfillmentProvider,
    ProductData,
    ProductListResult,
    ProviderOrderResult,
    ProviderOrderStatus,
    SyncResult,
    TrackingInfo,
)

logger = logging.getLogger(__name__)


_DEFAULT_CATALOG = "shop_engine.providers.local.LocalCatalogProvider"
_DEFAULT_FULFILLMENT = "shop_engine.providers.fulfillment_local.LocalFulfillmentProvider"


def _import_class(dotted: str) -> type:
    """Import ``"pkg.mod.Class"`` and return the class object.

    Raises ImportError with a clearer message than the raw exception so
    typos in settings produce actionable errors.
    """
    try:
        module_path, _, class_name = dotted.rpartition(".")
        if not module_path:
            raise ImportError(f"Not a dotted path: {dotted!r}")
        module = importlib.import_module(module_path)
        return getattr(module, class_name)
    except (ImportError, AttributeError) as exc:
        raise ImportError(
            f"Could not import provider {dotted!r}. Check the dotted "
            f"path in your settings. Original error: {exc}"
        ) from exc


def get_catalog_provider(**kwargs: Any) -> CatalogProvider:
    """Return an instance of the configured catalogue provider.

    Reads ``settings.SHOP_CATALOG_PROVIDER``, defaults to
    ``LocalCatalogProvider``. Any ``kwargs`` are forwarded to the
    provider's ``__init__``.
    """
    dotted = getattr(settings, "SHOP_CATALOG_PROVIDER", _DEFAULT_CATALOG)
    cls = _import_class(dotted)
    return cls(**kwargs)


def get_fulfillment_provider(**kwargs: Any) -> FulfillmentProvider:
    """Return an instance of the configured fulfillment provider."""
    dotted = getattr(settings, "SHOP_FULFILLMENT_PROVIDER", _DEFAULT_FULFILLMENT)
    cls = _import_class(dotted)
    return cls(**kwargs)
