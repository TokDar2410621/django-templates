"""Read-only queries for newsletter_engine.

All functions here are pure SELECTs. Mutation lives in ``services/``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from django.db.models import Count, Q, QuerySet
from django.utils import timezone

from .models import (
    AutomationEnrollment,
    Campaign,
    Delivery,
    MailingList,
    Membership,
    Subscriber,
    UnsubscribeToken,
)


# ---------------------------------------------------------------------------
# Subscribers
# ---------------------------------------------------------------------------
def get_subscriber_by_token(token: str) -> Optional[Subscriber]:
    """Resolve an unsubscribe / confirmation token to its subscriber."""
    tok = (
        UnsubscribeToken.objects
        .select_related("subscriber")
        .filter(token=token)
        .first()
    )
    return tok.subscriber if tok else None


def get_token(token: str) -> Optional[UnsubscribeToken]:
    return UnsubscribeToken.objects.select_related("subscriber").filter(token=token).first()


def active_subscribers_for_list(list: MailingList) -> QuerySet[Subscriber]:
    """Confirmed subscribers actively on a list."""
    return Subscriber.objects.filter(
        tenant=list.tenant,
        status=Subscriber.STATUS_CONFIRMED,
        memberships__list=list,
        memberships__status=Membership.STATUS_ACTIVE,
    ).distinct()


def bounce_offenders(tenant, *, threshold: int = 3) -> QuerySet[Subscriber]:
    """Subscribers whose soft-bounce count exceeds the threshold but who
    haven't been auto-suppressed yet (edge case — usually they hit hard
    immediately).
    """
    return Subscriber.objects.filter(
        tenant=tenant, bounce_count__gte=threshold,
    ).exclude(status=Subscriber.STATUS_BOUNCED)


# ---------------------------------------------------------------------------
# Automations
# ---------------------------------------------------------------------------
def due_enrollments(*, now: Optional[datetime] = None, limit: int = 500):
    """Re-exported from services for selector parity.

    See ``services.automations.due_enrollments`` for the canonical impl.
    """
    from .services.automations import due_enrollments as _due
    return _due(limit=limit, now=now)


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------
def recent_campaigns(tenant, *, n: int = 20) -> QuerySet[Campaign]:
    return (
        Campaign.objects
        .filter(tenant=tenant)
        .order_by("-created_at")[:n]
    )


def campaign_delivery_status(campaign: Campaign) -> dict[str, int]:
    """Return ``{status: count}`` for the campaign's deliveries.

    Reads from the Delivery table (live count), not the cached counters on
    Campaign — use this when you need the freshest progress view.
    """
    out: dict[str, int] = {}
    qs = (
        Delivery.objects
        .filter(campaign=campaign)
        .values("status")
        .annotate(n=Count("id"))
    )
    for row in qs:
        out[row["status"]] = row["n"]
    return out


# ---------------------------------------------------------------------------
# Scheduled campaigns (Celery beat target)
# ---------------------------------------------------------------------------
def campaigns_ready_to_send(*, now: Optional[datetime] = None) -> QuerySet[Campaign]:
    """Scheduled campaigns whose time has come."""
    now = now or timezone.now()
    return Campaign.objects.filter(
        status=Campaign.STATUS_SCHEDULED,
        scheduled_at__lte=now,
    )
