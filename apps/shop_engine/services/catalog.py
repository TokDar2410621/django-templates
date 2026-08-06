"""Catalogue sync — turn provider ``ProductData`` into local DB rows.

The local provider's ``sync_to_local`` is a no-op; this module is only
useful when an upstream provider (Alibaba, Gelato, your-own) needs to
materialize its catalogue into ``Product`` / ``ProductVariant`` rows so
the storefront can render them without hitting the upstream on every
page load.

Sync semantics
--------------
UPSERT on ``(provider, external_id)``. The provider name is stored on
``Product.provider`` so a second provider's products coexist with the
first's without colliding on slugs.

We compute a slug from the upstream title only on INSERT — once a row
exists, its slug is frozen so internal links / SEO don't break on every
sync.
"""
from __future__ import annotations

import logging
from typing import Optional

from django.db import transaction
from django.utils.text import slugify

from ..models import Category, Product, ProductVariant, ProviderSyncLog, Tag
from ..providers import get_catalog_provider
from ..providers.base import ProductData, SyncResult

logger = logging.getLogger(__name__)


@transaction.atomic
def upsert_from_provider_data(*, provider: str, data: ProductData) -> tuple[Product, bool, list[ProductVariant], list[ProductVariant]]:
    """UPSERT one ``ProductData`` into the local DB.

    Returns ``(product, created, variants_created, variants_updated)``.

    - Categories are looked up by slug and AUTO-CREATED if missing.
      That matches the typical sync workflow where the upstream's
      taxonomy doesn't 1:1 mirror ours but we still want a clean tree
      out of the box. Operator can rename / merge them later.
    - Tags are looked up by name + auto-created. Same rationale.
    - Variants are matched on ``sku`` (which is globally unique). A
      variant whose SKU disappears upstream is **left as-is** in our
      DB — we don't auto-delete because we'd lose order history
      references. Mark it inactive manually if needed.
    """
    category = _resolve_category(data.category_slug)
    tags = _resolve_tags(data.tag_names)

    defaults = {
        "title": data.title,
        "description": data.description,
        "base_price_cents": data.base_price_cents,
        "currency": data.currency,
        "images": data.images,
        "is_active": data.is_active,
        "category": category,
    }

    # Look up first so we can branch on insert-vs-update for the slug
    # (slug is only set on INSERT to avoid breaking SEO on every sync).
    existing = Product.objects.filter(provider=provider, external_id=data.external_id).first()
    if existing is None:
        defaults["slug"] = _ensure_unique_slug(
            data.slug or data.title,
            provider=provider, external_id=data.external_id,
        )
    product, created = Product.objects.update_or_create(
        provider=provider,
        external_id=data.external_id,
        defaults=defaults,
    )

    if tags:
        product.tags.set(tags)

    variants_created: list[ProductVariant] = []
    variants_updated: list[ProductVariant] = []
    for vdata in data.variants:
        variant, v_created = ProductVariant.objects.update_or_create(
            sku=vdata.sku,
            defaults={
                "product": product,
                "label": vdata.label,
                "price_cents": vdata.price_cents,
                "stock_quantity": vdata.stock_quantity,
                "track_inventory": vdata.track_inventory,
                "attributes": vdata.attributes,
                "weight_grams": vdata.weight_grams,
            },
        )
        (variants_created if v_created else variants_updated).append(variant)

    return product, created, variants_created, variants_updated


def sync_from_provider(provider_name: Optional[str] = None, *, force: bool = False) -> SyncResult:
    """Iterate the configured provider's catalogue and UPSERT into local DB.

    ``provider_name`` is informational only — used to decide which
    settings-resolved provider to call (in this template there's only
    one configured provider; for multi-provider setups extend
    ``get_catalog_provider`` to take a name).
    """
    provider = get_catalog_provider()
    result = SyncResult()

    try:
        upstream_result = provider.sync_to_local(force=force)
        # If the provider implements the full loop itself (rare —
        # ``sync_to_local`` typically defers to upsert_from_provider_data
        # via this module's loop), it can return its own SyncResult.
        if upstream_result.products_created or upstream_result.products_updated:
            return upstream_result
    except NotImplementedError as exc:
        # Stub provider — fall back to manual iteration via list_products.
        logger.info("Provider sync_to_local not implemented (%s); using manual iteration.", exc)

    page = 1
    while True:
        try:
            page_result = provider.list_products(page=page, page_size=100)
        except NotImplementedError as exc:
            ProviderSyncLog.objects.create(
                provider=provider.name,
                action="sync_from_provider",
                payload={"page": page},
                status=ProviderSyncLog.STATUS_ERROR,
                error_message=str(exc),
            )
            result.errors.append(str(exc))
            return result
        except Exception as exc:
            logger.exception("Provider list_products failed on page %d", page)
            ProviderSyncLog.objects.create(
                provider=provider.name,
                action="sync_from_provider",
                payload={"page": page},
                status=ProviderSyncLog.STATUS_ERROR,
                error_message=str(exc),
            )
            result.errors.append(str(exc))
            return result

        for data in page_result.products:
            try:
                _, created, v_created, v_updated = upsert_from_provider_data(
                    provider=provider.name, data=data,
                )
                if created:
                    result.products_created += 1
                else:
                    result.products_updated += 1
                result.variants_created += len(v_created)
                result.variants_updated += len(v_updated)
            except Exception as exc:
                logger.exception("UPSERT failed for product %s", data.external_id)
                ProviderSyncLog.objects.create(
                    provider=provider.name,
                    action="upsert_product",
                    external_id=data.external_id,
                    payload={"title": data.title},
                    status=ProviderSyncLog.STATUS_ERROR,
                    error_message=str(exc),
                )
                result.errors.append(f"{data.external_id}: {exc}")

        if page_result.next_page is None:
            break
        page = page_result.next_page

    ProviderSyncLog.objects.create(
        provider=provider.name,
        action="sync_from_provider",
        payload={
            "products_created": result.products_created,
            "products_updated": result.products_updated,
            "variants_created": result.variants_created,
            "variants_updated": result.variants_updated,
        },
        status=ProviderSyncLog.STATUS_OK if result.ok else ProviderSyncLog.STATUS_ERROR,
        error_message="; ".join(result.errors) if result.errors else "",
    )
    logger.info(
        "Catalog sync done (provider=%s): created=%d updated=%d errors=%d",
        provider.name, result.products_created, result.products_updated, len(result.errors),
    )
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _resolve_category(slug: Optional[str]) -> Optional[Category]:
    if not slug:
        return None
    norm = slugify(slug)
    category, _ = Category.objects.get_or_create(
        slug=norm, defaults={"name": slug, "is_active": True},
    )
    return category


def _resolve_tags(names: list[str]) -> list[Tag]:
    tags: list[Tag] = []
    for raw in names or []:
        name = (raw or "").strip()
        if not name:
            continue
        tag, _ = Tag.objects.get_or_create(name=name)
        tags.append(tag)
    return tags


def _ensure_unique_slug(base: str, *, provider: str, external_id: str) -> str:
    """Return a slug that's unique across the Product table.

    Slugifies ``base``; if that already exists, appends a short suffix
    derived from ``provider`` + ``external_id`` (deterministic so reruns
    don't drift).
    """
    candidate = slugify(base) or "product"
    if not Product.objects.filter(slug=candidate).exists():
        return candidate
    suffix = slugify(f"{provider}-{external_id}")[:16]
    return f"{candidate}-{suffix}"[:200]
