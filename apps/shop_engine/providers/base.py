"""Provider interface — Protocols + dataclasses.

Every provider implementation (local, Alibaba stub, Gelato stub,
your-own.py) implements these Protocols. They're typed with
``typing.Protocol`` rather than ABC so concrete classes don't need to
declare inheritance — duck typing with a typechecker safety net.

The dataclasses are the canonical wire shape returned from each method.
They intentionally don't 1:1 mirror our ORM rows — a provider talks in
terms of an *upstream* product, which we then materialize into our own
``Product`` rows via the sync workflow.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Catalogue dataclasses
# ---------------------------------------------------------------------------
@dataclass
class ProductVariantData:
    """One variant in a provider's catalogue."""

    sku: str
    label: str
    price_cents: Optional[int] = None
    stock_quantity: int = 0
    track_inventory: bool = True
    attributes: dict[str, Any] = field(default_factory=dict)
    weight_grams: int = 0


@dataclass
class ProductData:
    """One product in a provider's catalogue.

    Local sync materializes this into a ``Product`` row via
    ``services.catalog.sync_from_provider``. ``external_id`` is the
    upstream's primary key — used as the UPSERT key (along with
    ``provider``).
    """

    external_id: str
    title: str
    slug: str
    description: str = ""
    base_price_cents: int = 0
    currency: str = "CAD"
    images: list = field(default_factory=list)
    category_slug: Optional[str] = None
    tag_names: list[str] = field(default_factory=list)
    variants: list[ProductVariantData] = field(default_factory=list)
    is_active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProductListResult:
    products: list[ProductData]
    next_page: Optional[int] = None
    total: Optional[int] = None


@dataclass
class SyncResult:
    products_created: int = 0
    products_updated: int = 0
    variants_created: int = 0
    variants_updated: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


# ---------------------------------------------------------------------------
# Fulfillment dataclasses
# ---------------------------------------------------------------------------
@dataclass
class ProviderOrderResult:
    """Returned by ``FulfillmentProvider.create_order``."""

    external_order_id: str
    status: str = "submitted"
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderOrderStatus:
    """Returned by ``FulfillmentProvider.get_order_status``."""

    external_order_id: str
    status: str
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass
class TrackingInfo:
    """Returned by ``FulfillmentProvider.get_tracking``."""

    external_order_id: str
    carrier: str
    tracking_number: str
    tracking_url: Optional[str] = None
    raw_response: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------
@runtime_checkable
class CatalogProvider(Protocol):
    """Surface a provider must implement to ship products through this engine."""

    #: Short identifier — stored on ``Product.provider``. Used as a UPSERT key.
    name: str

    def list_products(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        **filters: Any,
    ) -> ProductListResult:
        """Page through the provider's catalogue.

        ``filters`` are provider-specific (category ID, keyword, etc.).
        Implementations should be conservative and document their
        supported filter keys.
        """
        ...

    def get_product(self, external_id: str) -> Optional[ProductData]:
        """Return a single product by its upstream ID, or None if missing."""
        ...

    def check_availability(self, sku: str, qty: int) -> bool:
        """True if ``qty`` units of ``sku`` are currently in stock upstream."""
        ...

    def sync_to_local(self, *, force: bool = False) -> SyncResult:
        """Materialize the provider's catalogue into our local ``Product`` rows.

        ``force=False`` (default) only updates rows whose ``updated_at``
        on the upstream is newer than our last sync. ``force=True``
        ignores that and re-writes everything.
        """
        ...


@runtime_checkable
class FulfillmentProvider(Protocol):
    """Surface a provider must implement to fulfill orders through this engine."""

    name: str

    def create_order(self, order: Any) -> ProviderOrderResult:
        """Dispatch an Order to the upstream fulfillment provider.

        ``order`` is a ``shop_engine.models.Order`` instance — typed as
        ``Any`` here to avoid a model import in the protocol module
        (which would break the layering: providers shouldn't import
        models directly in their type signatures; they should import
        them inside the method body).
        """
        ...

    def get_order_status(self, external_order_id: str) -> ProviderOrderStatus:
        """Poll the upstream for the current status of a dispatched order."""
        ...

    def cancel_order(self, external_order_id: str) -> bool:
        """Attempt to cancel an upstream order. Returns True on success."""
        ...

    def get_tracking(self, external_order_id: str) -> Optional[TrackingInfo]:
        """Return shipping tracking info if available, else None."""
        ...
