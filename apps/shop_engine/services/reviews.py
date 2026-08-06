"""Reviews — submit + auto-flag verified-purchase.

``submit_review`` creates a ``ProductReview`` row. If
``SHOP_REVIEW_REQUIRES_PURCHASE`` is True (default), the user must have
a paid Order containing the product, otherwise ``ReviewRequiresPurchase``
is raised. Set the toggle to False if you want to allow general public
reviews.

``is_verified_purchase`` is set at write time based on Order history.
The same flag is also flipped automatically by a signal in
``signals.py`` when a new Order is paid (covers the case where the user
reviewed before buying).
"""
from __future__ import annotations

import logging
from typing import Optional

from django.conf import settings
from django.db import transaction

from ..exceptions import ReviewRequiresPurchase
from ..models import Order, OrderItem, Product, ProductReview

logger = logging.getLogger(__name__)


def has_user_purchased(*, user, product: Product) -> bool:
    """True if the user has a paid Order containing the product."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return OrderItem.objects.filter(
        order__user=user,
        order__status__in=Order.PAID_STATUSES,
        product=product,
    ).exists()


@transaction.atomic
def submit_review(
    *,
    user,
    product: Product,
    rating: int,
    title: str = "",
    body: str = "",
) -> ProductReview:
    """Create or update the user's review of a product.

    One review per (user, product) — calling twice updates the existing
    row. Enforces the rating range (1–5) at the model layer too.
    """
    if not (1 <= int(rating) <= 5):
        raise ValueError("rating must be 1..5")

    requires_purchase = bool(getattr(settings, "SHOP_REVIEW_REQUIRES_PURCHASE", True))
    verified = has_user_purchased(user=user, product=product)
    if requires_purchase and not verified:
        raise ReviewRequiresPurchase(
            "You can only review products you've purchased."
        )

    review, _ = ProductReview.objects.update_or_create(
        product=product,
        user=user,
        defaults={
            "rating": rating,
            "title": title or "",
            "body": body or "",
            "is_verified_purchase": verified,
            "author_name_snapshot": _resolve_author_name(user),
        },
    )
    logger.info(
        "submit_review user=%s product=%s rating=%d verified=%s",
        user.pk, product.slug, rating, verified,
    )
    return review


def _resolve_author_name(user) -> str:
    """Best-effort display name for an auth user — covers the projects that override AUTH_USER_MODEL."""
    for attr in ("display_name", "get_full_name", "username", "email"):
        val = getattr(user, attr, None)
        if callable(val):
            try:
                val = val()
            except Exception:
                val = None
        if val:
            return str(val)
    return ""


def refresh_verified_flag_for_user_product(*, user, product: Product) -> None:
    """If a review exists, re-evaluate ``is_verified_purchase``.

    Called by the ``order_paid`` signal so the flag flips True the
    moment an Order containing the product becomes paid.
    """
    review = ProductReview.objects.filter(product=product, user=user).first()
    if review is None:
        return
    new_flag = has_user_purchased(user=user, product=product)
    if new_flag != review.is_verified_purchase:
        review.is_verified_purchase = new_flag
        review.save(update_fields=["is_verified_purchase", "updated_at"])
