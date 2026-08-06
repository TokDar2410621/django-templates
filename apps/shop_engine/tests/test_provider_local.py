"""LocalCatalogProvider + LocalFulfillmentProvider tests."""
from __future__ import annotations

import pytest

from shop_engine.models import Order
from shop_engine.providers.fulfillment_local import LocalFulfillmentProvider
from shop_engine.providers.local import LocalCatalogProvider


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_local_catalog_list_products(product, variant):
    p = LocalCatalogProvider()
    result = p.list_products()
    assert result.total == 1
    assert result.products[0].external_id == product.slug
    assert len(result.products[0].variants) == 1


@pytest.mark.django_db
def test_local_catalog_get_product_by_slug(product, variant):
    p = LocalCatalogProvider()
    data = p.get_product(product.slug)
    assert data is not None
    assert data.title == product.title


@pytest.mark.django_db
def test_local_catalog_get_product_missing(db):
    p = LocalCatalogProvider()
    assert p.get_product("does-not-exist") is None


@pytest.mark.django_db
def test_local_catalog_check_availability_in_stock(variant):
    p = LocalCatalogProvider()
    assert p.check_availability(variant.sku, 50) is True


@pytest.mark.django_db
def test_local_catalog_check_availability_out_of_stock(out_of_stock_variant):
    p = LocalCatalogProvider()
    assert p.check_availability(out_of_stock_variant.sku, 1) is False


@pytest.mark.django_db
def test_local_catalog_check_availability_unknown_sku(db):
    p = LocalCatalogProvider()
    assert p.check_availability("UNKNOWN-SKU", 1) is False


@pytest.mark.django_db
def test_local_catalog_sync_to_local_is_noop(db):
    p = LocalCatalogProvider()
    result = p.sync_to_local()
    assert result.ok
    assert result.products_created == 0


# ---------------------------------------------------------------------------
# Fulfillment
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_local_fulfillment_create_order(user, product, variant):
    from shop_engine.models import ProviderSyncLog
    order = Order.objects.create(
        user=user, email=user.email, status=Order.STATUS_PAID,
        subtotal_cents=100, total_cents=100,
    )
    p = LocalFulfillmentProvider()
    result = p.create_order(order)
    assert result.external_order_id == order.order_number
    assert ProviderSyncLog.objects.filter(action="create_order").exists()


@pytest.mark.django_db
def test_local_fulfillment_get_tracking_none_when_unset(user):
    order = Order.objects.create(
        user=user, email=user.email, status=Order.STATUS_PAID,
        subtotal_cents=100, total_cents=100,
    )
    p = LocalFulfillmentProvider()
    assert p.get_tracking(order.order_number) is None


@pytest.mark.django_db
def test_local_fulfillment_get_tracking_reads_metadata(user):
    order = Order.objects.create(
        user=user, email=user.email, status=Order.STATUS_PAID,
        subtotal_cents=100, total_cents=100,
        provider_metadata={
            "carrier": "Canada Post", "tracking_number": "CP123", "tracking_url": "https://x.y/z",
        },
    )
    p = LocalFulfillmentProvider()
    tracking = p.get_tracking(order.order_number)
    assert tracking is not None
    assert tracking.tracking_number == "CP123"
    assert tracking.carrier == "Canada Post"
