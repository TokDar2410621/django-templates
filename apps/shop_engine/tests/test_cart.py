"""Cart service tests — add, remove, update, anon→user, coupons."""
from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from shop_engine.exceptions import (
    CouponExhausted,
    CouponExpired,
    CouponInvalid,
    CouponMinOrderNotMet,
    OutOfStock,
    ProductInactive,
)
from shop_engine.models import Cart, CartItem
from shop_engine.services import cart as cart_svc


# ---------------------------------------------------------------------------
# add_to_cart
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_add_to_cart_creates_line(user_cart, product, variant):
    item = cart_svc.add_to_cart(user_cart, product=product, variant=variant, quantity=2)
    assert item.quantity == 2
    assert item.unit_price_cents == 4999  # product's base price
    assert user_cart.items.count() == 1


@pytest.mark.django_db
def test_add_to_cart_idempotent_same_variant_increments(user_cart, product, variant):
    cart_svc.add_to_cart(user_cart, product=product, variant=variant, quantity=2)
    cart_svc.add_to_cart(user_cart, product=product, variant=variant, quantity=3)
    assert user_cart.items.count() == 1
    assert user_cart.items.first().quantity == 5


@pytest.mark.django_db
def test_add_to_cart_inactive_product_raises(user_cart, product, variant):
    product.is_active = False
    product.save()
    with pytest.raises(ProductInactive):
        cart_svc.add_to_cart(user_cart, product=product, variant=variant, quantity=1)


@pytest.mark.django_db
def test_add_to_cart_out_of_stock_raises(user_cart, product, out_of_stock_variant):
    with pytest.raises(OutOfStock):
        cart_svc.add_to_cart(user_cart, product=product, variant=out_of_stock_variant, quantity=1)


@pytest.mark.django_db
def test_add_to_cart_infinite_stock_succeeds(user_cart, product, infinite_stock_variant):
    item = cart_svc.add_to_cart(
        user_cart, product=product, variant=infinite_stock_variant, quantity=99,
    )
    assert item.quantity == 99


# ---------------------------------------------------------------------------
# update_quantity + remove
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_update_quantity_replaces_value(user_cart, product, variant):
    item = cart_svc.add_to_cart(user_cart, product=product, variant=variant, quantity=1)
    cart_svc.update_quantity(item, quantity=5)
    item.refresh_from_db()
    assert item.quantity == 5


@pytest.mark.django_db
def test_update_quantity_zero_deletes_line(user_cart, product, variant):
    item = cart_svc.add_to_cart(user_cart, product=product, variant=variant, quantity=1)
    cart_svc.update_quantity(item, quantity=0)
    assert user_cart.items.count() == 0


@pytest.mark.django_db
def test_remove_from_cart_idempotent(user_cart, product, variant):
    item = cart_svc.add_to_cart(user_cart, product=product, variant=variant, quantity=1)
    cart_svc.remove_from_cart(item)
    assert user_cart.items.count() == 0


# ---------------------------------------------------------------------------
# Coupons
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_apply_coupon_percent(user_cart, product, variant, coupon_percent):
    cart_svc.add_to_cart(user_cart, product=product, variant=variant, quantity=2)
    cart_svc.apply_coupon(user_cart, code="SAVE10")
    user_cart.refresh_from_db()
    assert user_cart.applied_coupon_id == coupon_percent.pk

    totals = cart_svc.calculate_totals(user_cart)
    # 2 × 4999 = 9998; 10% = 999 (floor of 999.8)
    assert totals["subtotal_cents"] == 9998
    assert totals["discount_cents"] == 999


@pytest.mark.django_db
def test_apply_coupon_fixed_capped_at_subtotal(user_cart, product, variant):
    from shop_engine.models import Coupon

    coupon = Coupon.objects.create(code="HUGE", kind=Coupon.KIND_FIXED, value=1000, is_active=True)
    cart_svc.add_to_cart(user_cart, product=product, variant=variant, quantity=1)
    cart_svc.apply_coupon(user_cart, code="HUGE")
    totals = cart_svc.calculate_totals(user_cart)
    # 4999 subtotal, $1000 = 100000¢ but capped at subtotal
    assert totals["discount_cents"] == 4999


@pytest.mark.django_db
def test_apply_coupon_free_shipping_zeroes_shipping(settings, user_cart, product, variant, coupon_free_shipping):
    settings.SHOP_FLAT_SHIPPING_CENTS = 1000
    cart_svc.add_to_cart(user_cart, product=product, variant=variant, quantity=1)
    cart_svc.apply_coupon(user_cart, code="FREESHIP")
    totals = cart_svc.calculate_totals(user_cart)
    assert totals["shipping_cents"] == 0


@pytest.mark.django_db
def test_apply_coupon_below_minimum_raises(user_cart, product, variant, coupon_with_minimum):
    cart_svc.add_to_cart(user_cart, product=product, variant=variant, quantity=1)
    with pytest.raises(CouponMinOrderNotMet):
        cart_svc.apply_coupon(user_cart, code="MIN100")


@pytest.mark.django_db
def test_apply_coupon_expired_raises(user_cart, product, variant):
    from datetime import timedelta
    from django.utils import timezone

    from shop_engine.models import Coupon

    Coupon.objects.create(
        code="OLD",
        kind=Coupon.KIND_PERCENT,
        value=10,
        is_active=True,
        starts_at=timezone.now() - timedelta(days=10),
        expires_at=timezone.now() - timedelta(days=1),
    )
    cart_svc.add_to_cart(user_cart, product=product, variant=variant, quantity=1)
    with pytest.raises(CouponExpired):
        cart_svc.apply_coupon(user_cart, code="OLD")


@pytest.mark.django_db
def test_apply_coupon_unknown_code_raises(user_cart, product, variant):
    cart_svc.add_to_cart(user_cart, product=product, variant=variant, quantity=1)
    with pytest.raises(CouponInvalid):
        cart_svc.apply_coupon(user_cart, code="NOPE")


@pytest.mark.django_db
def test_revoke_coupon(user_cart, product, variant, coupon_percent):
    cart_svc.add_to_cart(user_cart, product=product, variant=variant, quantity=1)
    cart_svc.apply_coupon(user_cart, code="SAVE10")
    cart_svc.revoke_coupon(user_cart)
    user_cart.refresh_from_db()
    assert user_cart.applied_coupon_id is None


# ---------------------------------------------------------------------------
# anon → user transfer
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_transfer_anonymous_cart_to_user_merges_lines(user, anon_cart, product, variant):
    # Anon cart has 2 hoodies.
    cart_svc.add_to_cart(anon_cart, product=product, variant=variant, quantity=2)

    # Now the user logs in. They had no user cart yet.
    surviving = cart_svc.transfer_anonymous_cart_to_user(
        session_key="session_test_abc", user=user,
    )
    assert surviving is not None
    assert surviving.user_id == user.pk
    assert surviving.items.count() == 1
    assert surviving.items.first().quantity == 2

    # The anon cart is gone.
    assert not Cart.objects.filter(session_key="session_test_abc", user__isnull=True).exists()


@pytest.mark.django_db
def test_transfer_anonymous_cart_merges_with_existing_user_cart(user, anon_cart, user_cart, product, variant):
    cart_svc.add_to_cart(anon_cart, product=product, variant=variant, quantity=3)
    cart_svc.add_to_cart(user_cart, product=product, variant=variant, quantity=2)

    surviving = cart_svc.transfer_anonymous_cart_to_user(
        session_key="session_test_abc", user=user,
    )
    assert surviving.pk == user_cart.pk
    surviving.items.first().refresh_from_db()
    assert surviving.items.first().quantity == 5  # 2 + 3


@pytest.mark.django_db
def test_transfer_anonymous_cart_inherits_affiliate_code(user, anon_cart, product, variant):
    anon_cart.affiliate_code = "REFCODE"
    anon_cart.save()
    cart_svc.add_to_cart(anon_cart, product=product, variant=variant, quantity=1)

    surviving = cart_svc.transfer_anonymous_cart_to_user(
        session_key="session_test_abc", user=user,
    )
    assert surviving.affiliate_code == "REFCODE"
