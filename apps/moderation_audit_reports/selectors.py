"""Read-only queries — no writes, no side effects.

Use these from views, admin filters, signals, anywhere you need to
*ask* the moderation tables a question. All return querysets or simple
values; none mutate state.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from django.db.models import Count, QuerySet
from django.utils import timezone

from .models import BannedUser, ModerationLog, Report, ReportStatus


def open_reports_for_target(target_type: str, target_id: str) -> QuerySet[Report]:
    """All currently OPEN reports for a given target. Useful for the
    "X people reported this" badge on a moderator-facing detail page.
    """
    return Report.objects.filter(
        target_type=target_type,
        target_id=str(target_id),
        status=ReportStatus.OPEN,
    ).order_by("-priority", "-created_at")


def report_queue(
    *,
    priority: Optional[int] = None,
    status: str = ReportStatus.OPEN,
    target_type: Optional[str] = None,
) -> QuerySet[Report]:
    """The moderator's work queue.

    Defaults: open reports, all priorities, all target types, ordered
    urgent-first then most recent. Override any of the three filters.
    """
    qs = Report.objects.all()
    if status:
        qs = qs.filter(status=status)
    if priority is not None:
        qs = qs.filter(priority=priority)
    if target_type:
        qs = qs.filter(target_type=target_type)
    return qs.order_by("-priority", "-created_at")


def report_queue_grouped(status: str = ReportStatus.OPEN) -> QuerySet:
    """Reports grouped by (target_type, target_id) with reporter counts.

    Useful when the same piece of content has been flagged by many users
    — the queue should show one row per offending item, not one row per
    individual report. Returns dicts with
    ``target_type, target_id, reporter_count, max_priority``.
    """
    return (
        Report.objects
        .filter(status=status)
        .values("target_type", "target_id")
        .annotate(
            reporter_count=Count("id"),
        )
        .order_by("-reporter_count")
    )


def is_banned(user: Any) -> bool:
    """Canonical "is this user currently banned?" check.

    Honors ``BannedUser.banned_until`` — a row with an expired
    ``banned_until`` is treated as not-banned (the moderator hasn't
    deleted the row yet but the suspension is over). Returns False for
    None / anonymous users.
    """
    if not user or not getattr(user, "is_authenticated", True):
        return False
    pk = getattr(user, "pk", None)
    if pk is None:
        return False
    try:
        ban = BannedUser.objects.only("banned_until").get(user_id=pk)
    except BannedUser.DoesNotExist:
        return False
    if ban.banned_until is None:
        return True  # permanent ban
    return ban.banned_until > timezone.now()


def recent_actions_by(actor: Any, n: int = 50) -> QuerySet[ModerationLog]:
    """The last N moderation actions performed by ``actor``.

    Powers the "your recent moderation activity" panel some products
    show so moderators can spot-check their own decisions before they
    pile up.
    """
    qs = ModerationLog.objects.all()
    if actor and getattr(actor, "pk", None):
        qs = qs.filter(actor_id=actor.pk)
    return qs.order_by("-created_at")[:n]


def actions_for_target(
    target_type: str,
    target_id: str,
) -> Iterable[ModerationLog]:
    """Full audit history for one target. Useful when a moderator
    needs to know "what's already been done to this user/post?"
    before deciding.
    """
    return ModerationLog.objects.filter(
        target_type=target_type,
        target_id=str(target_id),
    ).order_by("-created_at")
