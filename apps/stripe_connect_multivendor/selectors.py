"""Read-only queries — never mutate state in here."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from django.contrib.auth import get_user_model
from django.db.models import QuerySet, Sum

from .models import Partner, Payout


def get_partner_by_user(user) -> Optional[Partner]:
    """Return the Partner profile for a User, or None."""
    return Partner.objects.filter(user=user).first()


def get_partner_by_user_id(user_id) -> Optional[Partner]:
    """Variant when you only have the ID handy."""
    User = get_user_model()
    try:
        return Partner.objects.select_related("user").get(user_id=user_id)
    except Partner.DoesNotExist:
        return None


def list_partners(*, active_only: bool = True) -> QuerySet[Partner]:
    """All partners, optionally filtered to active rows."""
    qs = Partner.objects.select_related("user").all()
    if active_only:
        qs = qs.filter(active=True)
    return qs.order_by("display_name")


def unverified_partners() -> QuerySet[Partner]:
    """Partners onboarded into the system but not yet able to receive transfers.

    Useful for an admin "needs follow-up" dashboard — these are folks
    whose OAuth flow either hasn't completed or whose Stripe account
    hasn't passed KYC.
    """
    return Partner.objects.filter(active=True, stripe_account_verified=False)


def payout_history(
    partner: Partner,
    *,
    since: Optional[datetime] = None,
    limit: int = 100,
) -> QuerySet[Payout]:
    """Recent payouts for one partner, newest first."""
    qs = partner.payouts.all()
    if since is not None:
        qs = qs.filter(created_at__gte=since)
    return qs.order_by("-created_at")[:limit]


def partner_balance_cents(partner: Partner) -> dict:
    """Aggregate amounts for one partner — paid / pending / failed.

    Returned dict keys: ``paid_cents``, ``pending_cents``,
    ``failed_cents``, ``reversed_cents``. Returns 0 for any bucket
    without payouts.
    """
    buckets = {
        Payout.STATUS_PAID: 0,
        Payout.STATUS_PENDING: 0,
        Payout.STATUS_FAILED: 0,
        Payout.STATUS_REVERSED: 0,
    }
    rows = (
        partner.payouts
        .values("status")
        .annotate(total=Sum("partner_amount_cents"))
    )
    for row in rows:
        buckets[row["status"]] = int(row["total"] or 0)
    return {
        "paid_cents": buckets[Payout.STATUS_PAID],
        "pending_cents": buckets[Payout.STATUS_PENDING],
        "failed_cents": buckets[Payout.STATUS_FAILED],
        "reversed_cents": buckets[Payout.STATUS_REVERSED],
    }
