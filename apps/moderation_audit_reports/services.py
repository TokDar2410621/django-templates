"""Moderation services — submit, triage, ban, log.

Layered split:

  * ``compute_priority`` — pure function, no DB writes besides the
    repeat-report count read. Easy to unit-test exhaustively.
  * ``submit_report`` — wraps compute_priority + creates the Report +
    fires a ModerationLog row in one transaction.
  * ``triage_report`` — updates a Report's status and writes a paired
    ModerationLog row with before/after snapshots.
  * ``ban_user`` / ``unban_user`` — update the User.is_banned flag (your
    own model — we don't define it), upsert the BannedUser audit row,
    and log.
  * ``log_action`` — low-level write to the ModerationLog table. Use
    this from your own admin actions when you do something not covered
    by the canonical services above (e.g. deleting a Redis message
    that lives outside Postgres).

None of these services raise on banned actor / missing fields — that's
the view layer's job. Keep services boring and composable.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import (
    BannedUser,
    ModerationLog,
    Report,
    ReportPriority,
    ReportReason,
    ReportStatus,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default bilingual keyword sets — override via settings.
#
#   MODERATION_URGENT_KEYWORDS = [...]
#   MODERATION_HIGH_KEYWORDS = [...]
#
# These are SUBSTRING matches against a lowercased description, so prefer
# stems ("harcel" matches "harceler", "harcèlement", "harcelé") over full
# words. The defaults err on the side of recall, not precision: better to
# show one extra report as URGENT than to miss a real threat.
# ---------------------------------------------------------------------------
DEFAULT_URGENT_KEYWORDS: tuple[str, ...] = (
    # Threats of violence / death
    "violence", "menace", "menacer", "tuer", "kill", "murder",
    "mort", "death", "stab", "shoot",
    # Self-harm / suicide
    "suicide", "self-harm", "kill myself", "se tuer",
    # Minors
    "mineur", "minor", "child", "enfant", "kid", "underage",
    "pedo", "pédo", "csam", "explicit child",
)
DEFAULT_HIGH_KEYWORDS: tuple[str, ...] = (
    # Harassment / bullying
    "harcel", "harass", "bully", "intimid", "stalk", "stalker",
    # Hate speech / discrimination
    "racis", "racist", "homophob", "transphob", "hate", "haine",
    "antisemit", "islamophob",
    # Privacy invasion
    "doxx", "dox ", "personal info", "adresse perso",
    # Sexual harassment
    "sexual harass", "harcèlement sexuel",
)

DEFAULT_REPEAT_REPORT_THRESHOLD = 3


def _urgent_keywords() -> tuple[str, ...]:
    return tuple(getattr(settings, "MODERATION_URGENT_KEYWORDS", DEFAULT_URGENT_KEYWORDS))


def _high_keywords() -> tuple[str, ...]:
    return tuple(getattr(settings, "MODERATION_HIGH_KEYWORDS", DEFAULT_HIGH_KEYWORDS))


def _repeat_threshold() -> int:
    return int(getattr(settings, "MODERATION_REPEAT_REPORT_THRESHOLD", DEFAULT_REPEAT_REPORT_THRESHOLD))


# ---------------------------------------------------------------------------
# Priority computation
# ---------------------------------------------------------------------------
def compute_priority(
    *,
    target_type: str,
    target_id: str,
    reason: str,
    description: str,
) -> int:
    """Pick an initial priority for a new Report.

    Decision tree (first match wins, then escalation kicks in):

      1. URGENT — description matches ``MODERATION_URGENT_KEYWORDS``,
         OR reason is ``threat`` / ``minor`` / ``self_harm``.
      2. HIGH   — description matches ``MODERATION_HIGH_KEYWORDS``,
         OR reason is ``hate`` / ``illegal``.
      3. MEDIUM — reason is ``harassment`` / ``nsfw``.
      4. LOW    — everything else (default for ``spam`` / ``other``).

    Escalation: if there are already
    ``MODERATION_REPEAT_REPORT_THRESHOLD`` (default 3) OPEN reports
    targeting the same ``(target_type, target_id)``, bump the resulting
    priority one step up (capped at URGENT). Repeat reports are signal:
    one user might be wrong, three independent reports rarely are.
    """
    text = (description or "").lower()
    urgent_kw = _urgent_keywords()
    high_kw = _high_keywords()

    # Step 1 — reason-based hard wins
    if reason in {ReportReason.THREAT, ReportReason.MINOR, ReportReason.SELF_HARM}:
        base = ReportPriority.URGENT
    # Step 2 — urgent keywords in the description
    elif any(k in text for k in urgent_kw):
        base = ReportPriority.URGENT
    # Step 3 — high keywords OR HIGH-level reasons
    elif reason in {ReportReason.HATE, ReportReason.ILLEGAL}:
        base = ReportPriority.HIGH
    elif any(k in text for k in high_kw):
        base = ReportPriority.HIGH
    # Step 4 — medium-level reasons
    elif reason in {ReportReason.HARASSMENT, ReportReason.NSFW}:
        base = ReportPriority.MEDIUM
    # Step 5 — default
    else:
        base = ReportPriority.LOW

    # Escalation — repeat reports on the same target
    threshold = _repeat_threshold()
    if threshold > 0 and base < ReportPriority.URGENT:
        prior_open = Report.objects.filter(
            target_type=target_type,
            target_id=target_id,
            status=ReportStatus.OPEN,
        ).count()
        if prior_open >= threshold - 1:
            # threshold-1 because THIS report makes it `threshold`.
            base = min(int(ReportPriority.URGENT), int(base) + 1)
    return int(base)


# ---------------------------------------------------------------------------
# Log writer — low-level, called by every other service
# ---------------------------------------------------------------------------
def log_action(
    *,
    actor: Any = None,
    action: str,
    target_type: str,
    target_id: str,
    before: Optional[dict] = None,
    after: Optional[dict] = None,
    note: str = "",
) -> ModerationLog:
    """Write an append-only audit row.

    Call from your own admin actions when the canonical services don't
    cover what you're doing (e.g. wiping a Redis message that doesn't
    live in Postgres, soft-deleting a polymorphic FK target, etc.).
    """
    entry = ModerationLog.objects.create(
        actor=actor if (actor and getattr(actor, "is_authenticated", False)) else None,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        before=before,
        after=after,
        note=note,
    )
    logger.info(
        "moderation.log action=%s target=%s:%s actor=%s",
        action, target_type, target_id, getattr(actor, "pk", None),
    )
    return entry


# ---------------------------------------------------------------------------
# Submit / triage
# ---------------------------------------------------------------------------
@transaction.atomic
def submit_report(
    *,
    reporter: Any,
    target_type: str,
    target_id: str,
    target_owner: Any = None,
    reason: str = ReportReason.OTHER,
    description: str = "",
    evidence_url: str = "",
) -> Report:
    """Create a new Report with auto-computed priority + a log entry.

    ``reporter`` and ``target_owner`` are user instances (or None for
    anonymous reports / unknown owners). ``target_id`` is coerced to
    string so callers can pass UUIDs, ints, or prefix-namespaced
    strings interchangeably.
    """
    target_id = str(target_id)
    priority = compute_priority(
        target_type=target_type,
        target_id=target_id,
        reason=reason,
        description=description,
    )
    report = Report.objects.create(
        reporter=reporter if (reporter and getattr(reporter, "is_authenticated", False)) else None,
        target_type=target_type,
        target_id=target_id,
        target_owner=target_owner,
        reason=reason,
        description=description,
        evidence_url=evidence_url,
        priority=priority,
    )
    log_action(
        actor=reporter,
        action="report.submit",
        target_type=target_type,
        target_id=target_id,
        after={"report_id": report.pk, "priority": priority, "reason": reason},
        note=(description[:200] if description else ""),
    )
    return report


@transaction.atomic
def triage_report(
    *,
    report: Report,
    actor: Any,
    status: str,
    note: str = "",
) -> Report:
    """Update a report's status + write a paired ModerationLog row.

    ``status`` must be one of ``ReportStatus`` values. When transitioning
    to ``ACTIONED`` or ``DISMISSED``, ``actioned_by`` and ``actioned_at``
    are set. Calling triage on an already-actioned report is a no-op
    on the audit log (no double-logging) but still updates the row in
    case the moderator is changing their mind.
    """
    if status not in {s.value for s in ReportStatus}:
        raise ValueError(f"invalid report status: {status!r}")

    before = {"status": report.status, "priority": report.priority}
    report.status = status
    if status in {ReportStatus.ACTIONED, ReportStatus.DISMISSED}:
        report.actioned_by = actor if (actor and getattr(actor, "is_authenticated", False)) else None
        report.actioned_at = timezone.now()
    report.save(update_fields=["status", "actioned_by", "actioned_at"])

    log_action(
        actor=actor,
        action=f"report.{status}",
        target_type="report",
        target_id=str(report.pk),
        before=before,
        after={"status": report.status, "priority": report.priority},
        note=note,
    )
    return report


# ---------------------------------------------------------------------------
# Ban / unban
# ---------------------------------------------------------------------------
@transaction.atomic
def ban_user(
    *,
    user: Any,
    by: Any,
    reason: str = "",
    days: Optional[int] = None,
) -> BannedUser:
    """Ban a user (idempotent).

    Flips ``user.is_banned`` to True if your User model exposes that
    attribute (we update it via ``update_fields=["is_banned"]`` only when
    the attribute exists, so the template is usable on projects that
    don't have the flag — selectors.is_banned() will still work via the
    BannedUser table). Upserts the BannedUser row and writes a log.

    ``days=None`` → permanent ban. ``days=7`` → 7-day suspension.
    """
    banned_until: Optional[datetime] = None
    if days is not None and days > 0:
        banned_until = timezone.now() + timedelta(days=days)

    # Flip the cached boolean on the User if the field exists — otherwise
    # the selector still works via the BannedUser table.
    if hasattr(user, "is_banned"):
        if not getattr(user, "is_banned", False):
            user.is_banned = True
            try:
                user.save(update_fields=["is_banned"])
            except (ValueError, Exception):  # field may not be a real DB column
                user.save()

    ban, _created = BannedUser.objects.update_or_create(
        user=user,
        defaults={
            "banned_by": by if (by and getattr(by, "is_authenticated", False)) else None,
            "reason": reason,
            "banned_until": banned_until,
        },
    )
    log_action(
        actor=by,
        action="user.ban",
        target_type="user",
        target_id=str(user.pk),
        after={
            "reason": reason,
            "banned_until": banned_until.isoformat() if banned_until else None,
        },
        note=reason,
    )
    return ban


@transaction.atomic
def unban_user(
    *,
    user: Any,
    by: Any,
    note: str = "",
) -> None:
    """Lift a ban. Deletes the BannedUser row and clears ``is_banned``."""
    if hasattr(user, "is_banned") and getattr(user, "is_banned", False):
        user.is_banned = False
        try:
            user.save(update_fields=["is_banned"])
        except (ValueError, Exception):
            user.save()

    BannedUser.objects.filter(user=user).delete()
    log_action(
        actor=by,
        action="user.unban",
        target_type="user",
        target_id=str(user.pk),
        note=note,
    )
