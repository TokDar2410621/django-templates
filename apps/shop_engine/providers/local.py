"""Local catalogue provider — serves products out of our own DB.

This is the default and matches the typical "operator manages products
in the admin" workflow. ``sync_to_local`` is a no-op (the local DB IS
the local catalogue). All other methods translate Product / Variant ORM
rows into the wire-shape dataclasses.

Use this provider whenever you don't need to import from an upstream
marketplace.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from django.db.models import Q

from ..models import Product, ProductVariant
from .base import (
    CatalogProvider,
    ProductData,
    ProductListResult,
    ProductVariantData,
    SyncResult,
)

logger = logging.getLogger(__name__)


class LocalCatalogProvider(CatalogProvider):
    """Catalogue stored in Django's own DB. The default provider."""

    name = "local"

    def __init__(self, **_: Any) -> None:
        # No configuration needed — local provider is always operable.
        pass

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
        """Return a page of active local products.

        Supported filters:

        - ``q`` — case-insensitive substring match on title + description.
        - ``category_slug`` — exact match on Product.category.slug.
        - ``tag_name`` — exact match on any of Product.tags.name.
        - ``min_price_cents`` / ``max_price_cents`` — bounds on base_price_cents.
        - ``is_featured`` — bool.
        """
        qs = Product.objects.filter(is_active=True, provider=Product.PROVIDER_LOCAL)

        q = filters.get("q")
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))

        if filters.get("category_slug"):
            qs = qs.filter(category__slug=filters["category_slug"])
        if filters.get("tag_name"):
            qs = qs.filter(tags__name=filters["tag_name"])
        if filters.get("min_price_cents") is not None:
            qs = qs.filter(base_price_cents__gte=int(filters["min_price_cents"]))
        if filters.get("max_price_cents") is not None:
            qs = qs.filter(base_price_cents__lte=int(filters["max_price_cents"]))
        if filters.get("is_featured") is not None:
            qs = qs.filter(is_featured=bool(filters["is_featured"]))

        qs = qs.prefetch_related("variants", "tags").distinct()
        total = qs.count()

        offset = (max(page, 1) - 1) * max(page_size, 1)
        rows = list(qs[offset:offset + page_size])

        products = [self._to_data(p) for p in rows]
        next_page = page + 1 if offset + page_size < total else None
        return ProductListResult(products=products, next_page=next_page, total=total)

    def get_product(self, external_id: str) -> Optional[ProductData]:
        """For the local provider, ``external_id`` is the product slug.

        Falls back to the numeric PK if the string is numeric — handy for
        admin shortcuts. Returns None for inactive products.
        """
        qs = Product.objects.filter(is_active=True).prefetch_related("variants", "tags")
        product: Optional[Product]
        product = qs.filter(slug=external_id).first()
        if product is None and external_id.isdigit():
            product = qs.filter(pk=int(external_id)).first()
        if product is None:
            return None
        return self._to_data(product)

    def check_availability(self, sku: str, qty: int) -> bool:
        """True if ``qty`` units of ``sku`` are in stock (or untracked)."""
        variant = ProductVariant.objects.filter(sku=sku, is_active=True).first()
        if variant is None:
            return False
        return variant.is_in_stock(qty)

    # ------------------------------------------------------------------
    # Sync — no-op for the local provider
    # ------------------------------------------------------------------
    def sync_to_local(self, *, force: bool = False) -> SyncResult:
        """No-op — the local DB IS the source of truth.

        Returns an empty, successful ``SyncResult`` so the task layer
        doesn't have to special-case the local provider.
        """
        logger.info("LocalCatalogProvider.sync_to_local — no-op (already local)")
        return SyncResult()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    @staticmethod
    def _to_data(product: Product) -> ProductData:
        return ProductData(
            external_id=product.slug,
            title=product.title,
            slug=product.slug,
            description=product.description,
            base_price_cents=int(product.base_price_cents),
            currency=product.currency,
            images=list(product.images or []),
            category_slug=product.category.slug if product.category_id else None,
            tag_names=[t.name for t in product.tags.all()],
            variants=[
                ProductVariantData(
                    sku=v.sku,
                    label=v.label,
                    price_cents=v.price_cents,
                    stock_quantity=int(v.stock_quantity),
                    track_inventory=v.track_inventory,
                    attributes=dict(v.attributes or {}),
                    weight_grams=int(v.weight_grams),
                )
                for v in product.variants.filter(is_active=True)
            ],
            is_active=product.is_active,
            metadata={},
        )
