"""Pytest fixtures + Stripe mock for shop_engine tests.

The Stripe SDK is mocked at module level so the test suite runs without
``stripe`` installed in CI. Fixtures cover the most-used objects:
products + variants, carts (anon + user), coupons, affiliates (both
flavours), and a fake catalog/fulfillment provider with call recording.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest
from django.contrib.auth import get_user_model

from shop_engine.models import (
    Affiliate,
    Cart,
    Category,
    Coupon,
    Product,
    ProductVariant,
)


# ---------------------------------------------------------------------------
# Stripe SDK mock — installed before services use it.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def stub_stripe(monkeypatch):
    """Provide a fake ``stripe`` module so checkout tests don't need the SDK."""
    fake = types.ModuleType("stripe")
    fake.api_key = None

    class StripeError(Exception):
        pass

    class SignatureVerificationError(StripeError):
        pass

    fake.error = types.SimpleNamespace(
        StripeError=StripeError,
        SignatureVerificationError=SignatureVerificationError,
    )
    fake.SignatureVerificationError = SignatureVerificationError

    fake.PaymentIntent = MagicMock(name="stripe.PaymentIntent")
    fake.PaymentIntent.create = MagicMock(
        return_value={"id": "pi_test_123", "client_secret": "cs_test_abc"},
    )
    fake.PaymentIntent.retrieve = MagicMock(
        return_value={"id": "pi_test_123", "client_secret": "cs_test_abc"},
    )
    fake.Refund = MagicMock(name="stripe.Refund")
    fake.Refund.create = MagicMock(return_value={"id": "re_test_xyz"})
    fake.Charge = MagicMock(name="stripe.Charge")
    fake.Charge.list = MagicMock(
        return_value={"data": [{"amount_refunded": 0}]},
    )
    fake.Webhook = MagicMock(name="stripe.Webhook")
    fake.Webhook.construct_event = MagicMock()

    monkeypatch.setitem(sys.modules, "stripe", fake)
    from django.conf import settings as dj_settings
    dj_settings.STRIPE_SECRET_KEY = "sk_test_fake"
    dj_settings.STRIPE_WEBHOOK_SECRET = "whsec_fake"
    yield fake


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
@pytest.fixture
def user(db):
    User = get_user_model()
    return User.objects.create_user(
        username="alice", email="alice@example.com", password="pw_pw_pw_pw",
    )


@pytest.fixture
def other_user(db):
    User = get_user_model()
    return User.objects.create_user(
        username="bob", email="bob@example.com", password="pw_pw_pw_pw",
    )


@pytest.fixture
def admin_user(db):
    User = get_user_model()
    return User.objects.create_superuser(
        username="admin", email="admin@example.com", password="adminpw",
    )


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------
@pytest.fixture
def category(db) -> Category:
    return Category.objects.create(name="Apparel", slug="apparel", is_active=True)


@pytest.fixture
def product(db, category) -> Product:
    return Product.objects.create(
        title="Test Hoodie",
        slug="test-hoodie",
        category=category,
        is_active=True,
        base_price_cents=4999,
        currency="CAD",
        images=[{"url": "https://example.com/hoodie.jpg", "is_primary": True}],
    )


@pytest.fixture
def variant(db, product) -> ProductVariant:
    return ProductVariant.objects.create(
        product=product,
        sku="HOODIE-L",
        label="Large",
        price_cents=None,  # falls back to product
        stock_quantity=100,
        track_inventory=True,
        attributes={"size": "L"},
    )


@pytest.fixture
def out_of_stock_variant(db, product) -> ProductVariant:
    return ProductVariant.objects.create(
        product=product,
        sku="HOODIE-XS",
        label="XS (out of stock)",
        stock_quantity=0,
        track_inventory=True,
    )


@pytest.fixture
def infinite_stock_variant(db, product) -> ProductVariant:
    return ProductVariant.objects.create(
        product=product,
        sku="HOODIE-DIGITAL",
        label="Digital",
        stock_quantity=0,
        track_inventory=False,  # infinite
    )


# ---------------------------------------------------------------------------
# Carts
# ---------------------------------------------------------------------------
@pytest.fixture
def user_cart(db, user) -> Cart:
    return Cart.objects.create(user=user)


@pytest.fixture
def anon_cart(db) -> Cart:
    return Cart.objects.create(session_key="session_test_abc")


# ---------------------------------------------------------------------------
# Coupons
# ---------------------------------------------------------------------------
@pytest.fixture
def coupon_percent(db) -> Coupon:
    return Coupon.objects.create(
        code="SAVE10",
        kind=Coupon.KIND_PERCENT,
        value=10,
        is_active=True,
    )


@pytest.fixture
def coupon_fixed(db) -> Coupon:
    return Coupon.objects.create(
        code="OFF5",
        kind=Coupon.KIND_FIXED,
        value=5,  # $5
        is_active=True,
    )


@pytest.fixture
def coupon_free_shipping(db) -> Coupon:
    return Coupon.objects.create(
        code="FREESHIP",
        kind=Coupon.KIND_FREE_SHIPPING,
        value=0,
        is_active=True,
    )


@pytest.fixture
def coupon_with_minimum(db) -> Coupon:
    return Coupon.objects.create(
        code="MIN100",
        kind=Coupon.KIND_PERCENT,
        value=10,
        minimum_order_cents=10000,  # $100
        is_active=True,
    )


# ---------------------------------------------------------------------------
# Affiliates
# ---------------------------------------------------------------------------
@pytest.fixture
def affiliate_user_based(db, other_user) -> Affiliate:
    return Affiliate.objects.create(
        user=other_user,
        email=other_user.email,
        display_name="Bob the Affiliate",
        commission_bps=1500,  # 15%
        status=Affiliate.STATUS_ACTIVE,
    )


@pytest.fixture
def affiliate_email_only(db) -> Affiliate:
    from shop_engine.models import _new_magic_link_token

    return Affiliate.objects.create(
        user=None,
        email="influencer@example.com",
        display_name="External Influencer",
        commission_bps=2000,  # 20%
        flat_per_order_cents=500,
        status=Affiliate.STATUS_ACTIVE,
        magic_link_token=_new_magic_link_token(),
    )


# ---------------------------------------------------------------------------
# Fake providers — recording calls for assertion.
# ---------------------------------------------------------------------------
class _RecordingFulfillmentProvider:
    """Test double for ``FulfillmentProvider``."""

    name = "test"

    def __init__(self, **_):
        self.created_orders = []
        self.cancelled_orders = []

    def create_order(self, order):
        from shop_engine.providers.base import ProviderOrderResult
        self.created_orders.append(order.order_number)
        return ProviderOrderResult(
            external_order_id=f"test_ext_{order.order_number}",
            status="submitted",
            raw_response={"test": True},
        )

    def get_order_status(self, external_order_id):
        from shop_engine.providers.base import ProviderOrderStatus
        return ProviderOrderStatus(external_order_id=external_order_id, status="submitted")

    def cancel_order(self, external_order_id):
        self.cancelled_orders.append(external_order_id)
        return True

    def get_tracking(self, external_order_id):
        return None


@pytest.fixture
def fake_fulfillment_provider(monkeypatch):
    provider = _RecordingFulfillmentProvider()
    monkeypatch.setattr(
        "shop_engine.services.fulfillment.get_fulfillment_provider",
        lambda **_: provider,
    )
    return provider
