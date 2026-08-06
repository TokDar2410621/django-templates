"""Read-only queries — selectors layer.

Anything that doesn't write goes here. Keeps services.py focused on
mutations, and lets views import lean read paths without pulling in
side-effect-y service code.

Naming convention: ``<noun>_<scope>`` or ``<verb>_<noun>`` —
``active_products``, ``cart_for_request``, ``order_history``.
"""
from __future__ import annotations

from typing import Optional

from django.db.models import Q, QuerySet

from .models import (
    Affiliate,
    AffiliateConversion,
    AffiliatePayout,
    Cart,
    Category,
    Order,
    Product,
    ProductReview,
)
from .services.cart import get_or_create_cart_for_request as cart_for_request  # noqa: F401 — re-export


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------
def active_products() -> QuerySet[Product]:
    """All currently-purchasable products."""
    return Product.objects.filter(is_active=True).select_related("category").prefetch_related("variants", "tags")


def featured_products(limit: int = 8) -> QuerySet[Product]:
    """Active products flagged ``is_featured=True``, ordered newest first."""
    return active_products().filter(is_featured=True)[:limit]


def category_tree() -> list[dict]:
    """Nested dict tree of active categories — ``[{id, slug, name, children: [...]}, ...]``.

    Two-pass so we don't N+1 on deep trees. ``children`` keys are
    omitted when empty for a compact frontend payload.
    """
    rows = list(Category.objects.filter(is_active=True).order_by("order", "name"))
    by_parent: dict[Optional[int], list[Category]] = {}
    for row in rows:
        by_parent.setdefault(row.parent_id, []).append(row)

    def build(parent_id: Optional[int]) -> list[dict]:
        result: list[dict] = []
        for c in by_parent.get(parent_id, []):
            entry = {"id": c.pk, "slug": c.slug, "name": c.name}
            kids = build(c.pk)
            if kids:
                entry["children"] = kids
            result.append(entry)
        return result

    return build(None)


def reviews_for_product(product: Product) -> QuerySet[ProductReview]:
    return product.reviews.filter(is_published=True).select_related("user")


# ---------------------------------------------------------------------------
# Cart
# ---------------------------------------------------------------------------
def cart_with_items(cart: Cart) -> Cart:
    """Refresh the cart with related items prefetched."""
    return (
        Cart.objects
        .prefetch_related("items__product", "items__variant")
        .select_related("applied_coupon", "user")
        .get(pk=cart.pk)
    )


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
def order_history(user, *, n: int = 20) -> QuerySet[Order]:
    return (
        Order.objects
        .filter(user=user)
        .prefetch_related("items")
        .order_by("-created_at")[:n]
    )


def order_for_user(*, user, order_number: str) -> Optional[Order]:
    return Order.objects.filter(user=user, order_number=order_number).prefetch_related("items").first()


def order_for_email(*, email: str, order_number: str) -> Optional[Order]:
    """Look up a guest order — email is the only auth check we can do."""
    return Order.objects.filter(email__iexact=email, order_number=order_number).prefetch_related("items").first()


# ---------------------------------------------------------------------------
# Affiliates
# ---------------------------------------------------------------------------
def affiliate_dashboard_data(affiliate: Affiliate) -> dict:
    """Big summary blob for the affiliate dashboard.

    Shape::

        {
            "affiliate": {code, status, commission_bps, ...},
            "clicks": {total, last_30d},
            "conversions": {pending, approved, paid, count, total_commission_cents},
            "payouts": {pending_cents, paid_cents, history: [...]},
        }
    """
    from datetime import timedelta
    from django.utils import timezone

    cutoff_30d = timezone.now() - timedelta(days=30)
    clicks_30d = affiliate.clicks.filter(created_at__gte=cutoff_30d).count()

    pending = affiliate.conversions.filter(status=AffiliateConversion.STATUS_PENDING)
    approved = affiliate.conversions.filter(status=AffiliateConversion.STATUS_APPROVED)
    paid = affiliate.conversions.filter(status=AffiliateConversion.STATUS_PAID)
    pending_payouts = affiliate.payouts.filter(status=AffiliatePayout.STATUS_PENDING)

    return {
        "affiliate": {
            "code": affiliate.code,
            "display_name": affiliate.display_name,
            "status": affiliate.status,
            "commission_bps": affiliate.commission_bps,
            "flat_per_order_cents": affiliate.flat_per_order_cents,
        },
        "clicks": {
            "total": affiliate.total_clicks,
            "last_30d": clicks_30d,
        },
        "conversions": {
            "pending_count": pending.count(),
            "pending_cents": sum(int(c.commission_cents) for c in pending),
            "approved_count": approved.count(),
            "approved_cents": sum(int(c.commission_cents) for c in approved),
            "paid_count": paid.count(),
            "paid_cents": sum(int(c.commission_cents) for c in paid),
            "total_count": affiliate.total_conversions,
        },
        "payouts": {
            "pending_count": pending_payouts.count(),
            "pending_cents": sum(int(p.net_cents) for p in pending_payouts),
            "paid_cents": int(affiliate.total_paid_cents),
        },
    }


def pending_payouts_summary() -> dict:
    """Operator overview — total pending across all affiliates."""
    pending = AffiliatePayout.objects.filter(status=AffiliatePayout.STATUS_PENDING)
    return {
        "count": pending.count(),
        "affiliates": pending.values("affiliate__code").distinct().count(),
        "total_cents": sum(int(p.net_cents) for p in pending),
    }


# ---------------------------------------------------------------------------
# Money formatting
# ---------------------------------------------------------------------------
def cents_to_display(cents: int, currency: str = "CAD") -> str:
    """``2599 → "25.99 CAD"`` — for templates / receipts that prefer strings."""
    return f"{int(cents) / 100:.2f} {currency}"
