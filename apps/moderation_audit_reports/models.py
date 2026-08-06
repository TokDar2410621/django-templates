"""Moderation models — Report, BannedUser, ModerationLog.

The trio you need to run a healthy user-generated-content product:

  * ``Report`` — a generic content report. ``target_type`` + ``target_id``
    are deliberately string-based so you can flag a Redis message UUID
    (``"message"`` / ``"<uuid>"``), a PostgreSQL post (``"post"`` /
    ``"42"``), a comment (``"comment"`` / ``"c_18a..."``), or a
    prefix-namespaced item (``"message"`` / ``"conv_msg:<uuid>"``)
    without a polymorphic FK.
  * ``BannedUser`` — audit-only ban record. The "is this user banned?"
    gate lives on your User model (``user.is_banned`` boolean), but the
    record of who banned whom, when, and why lives here so it survives
    user deletion attempts and integrates with the moderator dashboard.
  * ``ModerationLog`` — append-only audit trail. Every moderator action
    (resolve, dismiss, delete content, ban, unban) writes a row. The
    admin has ``has_add_permission=False`` so logs cannot be back-dated
    or fabricated through the UI; only ``services.log_action()`` writes.

Priority is auto-computed by ``services.compute_priority`` (pure
function, easy to unit-test). Keyword sets are configurable through
``MODERATION_URGENT_KEYWORDS`` and ``MODERATION_HIGH_KEYWORDS`` settings
— defaults cover the bilingual FR/EN ground (threats, minors, hate,
doxxing) but you'll likely want to tune them per product / locale.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


# ---------------------------------------------------------------------------
# Configurable choices — override in your project's settings.
# ---------------------------------------------------------------------------
DEFAULT_TARGET_TYPES: list[tuple[str, str]] = [
    ("message", "Message"),
    ("post",    "Post"),
    ("comment", "Comment"),
    ("user",    "User profile"),
    ("media",   "Media"),
]


def _target_types() -> list[tuple[str, str]]:
    return list(getattr(settings, "MODERATION_TARGET_TYPES", DEFAULT_TARGET_TYPES))


class ReportReason(models.TextChoices):
    SPAM = "spam", "Spam"
    HARASSMENT = "harassment", "Harassment"
    THREAT = "threat", "Threat / violence"
    ILLEGAL = "illegal", "Illegal content"
    HATE = "hate", "Hate speech"
    NSFW = "nsfw", "NSFW / explicit"
    SELF_HARM = "self_harm", "Self-harm"
    MINOR = "minor", "Involves a minor"
    OTHER = "other", "Other"


class ReportStatus(models.TextChoices):
    OPEN = "open", "Open"
    TRIAGED = "triaged", "Triaged"
    ACTIONED = "actioned", "Actioned"
    DISMISSED = "dismissed", "Dismissed"


class ReportPriority(models.IntegerChoices):
    LOW = 0, "Low"
    MEDIUM = 1, "Medium"
    HIGH = 2, "High"
    URGENT = 3, "Urgent"


class Report(models.Model):
    """A user-submitted content report.

    ``target_id`` is a string (max 100 chars) so it can hold a bare UUID
    (36 chars), a PG integer PK, OR a prefix-namespaced id like
    ``conv_msg:<uuid>`` when the same ``target_type`` covers multiple
    sub-kinds. 100 leaves room for future prefixes without a migration.
    """

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports_filed",
        help_text="The user who filed this report. Null = anonymous report.",
    )
    target_type = models.CharField(
        max_length=32,
        choices=_target_types(),
        db_index=True,
        help_text="What kind of object is being reported (message, post, …).",
    )
    target_id = models.CharField(
        max_length=100,
        db_index=True,
        help_text=(
            "Identifier of the reported object. Free-form string so it can "
            "hold UUIDs, integer PKs, or prefix-namespaced ids "
            "(e.g. 'conv_msg:<uuid>')."
        ),
    )
    target_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports_received",
        help_text=(
            "The user who authored the reported content. Null if unknown "
            "(content sent anonymously, deleted user, etc.). The 'ban target' "
            "button on the admin acts on this user."
        ),
    )
    reason = models.CharField(
        max_length=32,
        choices=ReportReason.choices,
        default=ReportReason.OTHER,
        db_index=True,
    )
    description = models.TextField(
        blank=True,
        help_text="Free-form description from the reporter (also feeds priority compute).",
    )
    evidence_url = models.URLField(
        blank=True,
        help_text="Optional URL (screenshot, related conversation, etc.).",
    )

    priority = models.PositiveSmallIntegerField(
        choices=ReportPriority.choices,
        default=ReportPriority.MEDIUM,
        db_index=True,
        help_text="Auto-computed at submit time; admins can bump/lower from the panel.",
    )
    status = models.CharField(
        max_length=16,
        choices=ReportStatus.choices,
        default=ReportStatus.OPEN,
        db_index=True,
    )

    actioned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports_actioned",
    )
    actioned_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "moderation_report"
        # Urgent first, then most recent: the admin queue lands on the
        # work-that-matters without manual sorting.
        ordering = ("-priority", "-created_at")
        indexes = [
            models.Index(fields=["target_type", "target_id"]),
            models.Index(fields=["status", "-priority"]),
        ]

    def __str__(self) -> str:
        return (
            f"Report {self.pk} {self.target_type}:{self.target_id[:12]} "
            f"({self.get_status_display()})"
        )


class BannedUser(models.Model):
    """Audit-only ban record.

    The "is this user banned?" gate is your own ``User.is_banned``
    boolean (or equivalent) — that's the field your auth flow checks on
    every request. This row only records *who* banned the user, *when*,
    *why*, and (optionally) *until when* for time-limited bans.

    See ``selectors.is_banned`` for the canonical check that also honors
    ``banned_until`` expiry.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ban_record",
    )
    banned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bans_issued",
    )
    reason = models.TextField(blank=True)
    banned_until = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Null = permanent. Otherwise the ban expires at this datetime.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "moderation_banned_user"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        suffix = "permanent" if self.banned_until is None else f"until {self.banned_until:%Y-%m-%d}"
        return f"Banned {self.user_id} ({suffix})"


class ModerationLog(models.Model):
    """Append-only audit trail of every moderator action.

    Rows are written by ``services.log_action()``; the admin disables
    add-permission so logs cannot be fabricated through the UI. ``before``
    and ``after`` are JSONFields so you can capture a diff snapshot of
    whatever model the action touched (Report status, User.is_banned,
    Message content, etc.) without coupling the log table to any
    particular schema.
    """

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="moderation_actions",
        help_text="The admin who performed the action. Null for system actions.",
    )
    action = models.CharField(
        max_length=64,
        db_index=True,
        help_text=(
            "Free-form action name, e.g. 'report.triage', 'user.ban', "
            "'message.delete'. Keep them dotted+lowercase for greppability."
        ),
    )
    target_type = models.CharField(max_length=32, db_index=True)
    target_id = models.CharField(max_length=100, db_index=True)

    before = models.JSONField(blank=True, null=True)
    after = models.JSONField(blank=True, null=True)
    note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "moderation_log"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["target_type", "target_id"]),
        ]

    def __str__(self) -> str:
        who = getattr(self.actor, "username", None) or "system"
        return f"{who} {self.action} {self.target_type}:{self.target_id[:12]} @ {self.created_at:%Y-%m-%d %H:%M}"
