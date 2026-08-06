"""Review submission + verified-purchase flag tests."""
from __future__ import annotations

import pytest

from shop_engine.exceptions import ReviewRequiresPurchase
from shop_engine.models import Order, OrderItem, ProductReview
from shop_engine.services import reviews as reviews_svc


@pytest.mark.django_db
def test_submit_review_requires_purchase_when_setting_on(settings, user, product):
    settings.SHOP_REVIEW_REQUIRES_PURCHASE = True
    with pytest.raises(ReviewRequiresPurchase):
        reviews_svc.submit_review(user=user, product=product, rating=5)


@pytest.mark.django_db
def test_submit_review_open_when_setting_off(settings, user, product):
    settings.SHOP_REVIEW_REQUIRES_PURCHASE = False
    review = reviews_svc.submit_review(user=user, product=product, rating=4, title="Nice", body="Loved it.")
    assert review.rating == 4
    assert review.is_verified_purchase is False


@pytest.mark.django_db
def test_submit_review_after_purchase_is_verified(settings, user, product, variant):
    settings.SHOP_REVIEW_REQUIRES_PURCHASE = True
    order = Order.objects.create(
        user=user, email=user.email, status=Order.STATUS_PAID,
        subtotal_cents=100, total_cents=100,
    )
    OrderItem.objects.create(
        order=order, product=product, variant=variant,
        product_title=product.title, sku=variant.sku,
        unit_price_cents=100, quantity=1, line_total_cents=100,
    )
    review = reviews_svc.submit_review(user=user, product=product, rating=5)
    assert review.is_verified_purchase is True


@pytest.mark.django_db
def test_submit_review_rating_out_of_range_raises(settings, user, product):
    settings.SHOP_REVIEW_REQUIRES_PURCHASE = False
    with pytest.raises(ValueError):
        reviews_svc.submit_review(user=user, product=product, rating=6)


@pytest.mark.django_db
def test_submit_review_update_existing_overwrites(settings, user, product):
    settings.SHOP_REVIEW_REQUIRES_PURCHASE = False
    reviews_svc.submit_review(user=user, product=product, rating=2)
    reviews_svc.submit_review(user=user, product=product, rating=5, title="Changed my mind")
    review = ProductReview.objects.get(user=user, product=product)
    assert review.rating == 5
    assert review.title == "Changed my mind"


@pytest.mark.django_db
def test_signal_flips_verified_when_order_paid(settings, user, product, variant):
    """Posting a review before purchase, then completing the purchase, flips the flag."""
    settings.SHOP_REVIEW_REQUIRES_PURCHASE = False
    reviews_svc.submit_review(user=user, product=product, rating=3)
    review = ProductReview.objects.get(user=user, product=product)
    assert review.is_verified_purchase is False

    # Create order in AWAITING then transition to PAID (so the signal fires).
    order = Order.objects.create(
        user=user, email=user.email, status=Order.STATUS_AWAITING_PAYMENT,
        subtotal_cents=100, total_cents=100,
    )
    OrderItem.objects.create(
        order=order, product=product, variant=variant,
        product_title=product.title, sku=variant.sku,
        unit_price_cents=100, quantity=1, line_total_cents=100,
    )
    order.status = Order.STATUS_PAID
    order.save()

    review.refresh_from_db()
    assert review.is_verified_purchase is True
