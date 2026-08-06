"""Tests for the stub providers — they must raise NotImplementedError with helpful messages.

These are documentation-as-test: each test pins the public surface so a
later change can't silently turn a stub into a "succeeds, returns None"
trap.
"""
from __future__ import annotations

import pytest

from shop_engine.exceptions import ProviderNotConfigured
from shop_engine.models import Order
from shop_engine.providers.alibaba_stub import AlibabaCatalogProvider
from shop_engine.providers.gelato_stub import GelatoFulfillmentProvider


# ---------------------------------------------------------------------------
# Alibaba
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_alibaba_stub_requires_credentials(settings):
    settings.ALIBABA_APP_KEY = ""
    settings.ALIBABA_APP_SECRET = ""
    settings.ALIBABA_ACCESS_TOKEN = ""
    p = AlibabaCatalogProvider()
    with pytest.raises(ProviderNotConfigured):
        p.list_products()


@pytest.mark.django_db
def test_alibaba_stub_list_products_with_creds_raises_not_implemented(settings):
    settings.ALIBABA_APP_KEY = "fake"
    settings.ALIBABA_APP_SECRET = "fake"
    settings.ALIBABA_ACCESS_TOKEN = "fake"
    p = AlibabaCatalogProvider()
    with pytest.raises(NotImplementedError) as exc:
        p.list_products()
    assert "stub" in str(exc.value).lower()


@pytest.mark.django_db
def test_alibaba_stub_get_product_raises(settings):
    settings.ALIBABA_APP_KEY = "fake"
    settings.ALIBABA_APP_SECRET = "fake"
    settings.ALIBABA_ACCESS_TOKEN = "fake"
    p = AlibabaCatalogProvider()
    with pytest.raises(NotImplementedError):
        p.get_product("external_id_123")


# ---------------------------------------------------------------------------
# Gelato
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_gelato_stub_requires_api_key(settings, user):
    settings.GELATO_API_KEY = ""
    order = Order.objects.create(
        user=user, email=user.email, status=Order.STATUS_PAID,
        subtotal_cents=100, total_cents=100,
    )
    p = GelatoFulfillmentProvider()
    with pytest.raises(ProviderNotConfigured):
        p.create_order(order)


@pytest.mark.django_db
def test_gelato_stub_create_order_raises_not_implemented(settings, user):
    settings.GELATO_API_KEY = "fake"
    order = Order.objects.create(
        user=user, email=user.email, status=Order.STATUS_PAID,
        subtotal_cents=100, total_cents=100,
    )
    p = GelatoFulfillmentProvider()
    with pytest.raises(NotImplementedError):
        p.create_order(order)


@pytest.mark.django_db
def test_gelato_stub_get_tracking_raises(settings):
    settings.GELATO_API_KEY = "fake"
    p = GelatoFulfillmentProvider()
    with pytest.raises(NotImplementedError):
        p.get_tracking("gel_ord_xxx")
