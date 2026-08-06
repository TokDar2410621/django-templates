"""Serializers for the moderation API.

Two surfaces:

  * **Public** — ``ReportSubmitSerializer``: what an end-user POSTs to
    report something. Strict whitelisting; no priority / status fields
    (those are server-side only).
  * **Admin** — ``ReportListSerializer`` and ``ReportDetailSerializer``:
    what the moderator's panel renders. Read-only by convention; actions
    go through dedicated triage endpoints.
"""
from __future__ import annotations

from rest_framework import serializers

from .models import BannedUser, ModerationLog, Report, ReportReason, ReportStatus


# ---------------------------------------------------------------------------
# Public — submit
# ---------------------------------------------------------------------------
class ReportSubmitSerializer(serializers.Serializer):
    """Inbound payload for POST /api/moderation/reports/."""

    target_type = serializers.CharField(max_length=32)
    target_id = serializers.CharField(max_length=100)
    target_owner_id = serializers.CharField(
        required=False, allow_blank=True, default="",
        help_text="Optional: user id of the content author, if known.",
    )
    reason = serializers.ChoiceField(
        choices=ReportReason.choices,
        default=ReportReason.OTHER,
    )
    description = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=2000,
    )
    evidence_url = serializers.URLField(
        required=False, allow_blank=True, default="",
    )

    def validate_target_type(self, value: str) -> str:
        # Allow ANY value the project has registered. Validation against
        # the configured ``MODERATION_TARGET_TYPES`` happens lazily so
        # adding new types via settings doesn't require a serializer edit.
        from .models import _target_types
        allowed = {code for code, _ in _target_types()}
        if allowed and value not in allowed:
            raise serializers.ValidationError(
                f"Unknown target_type {value!r}. Allowed: {sorted(allowed)}"
            )
        return value


# ---------------------------------------------------------------------------
# Admin — list / detail
# ---------------------------------------------------------------------------
class ReportListSerializer(serializers.ModelSerializer):
    """One row of the admin queue. Slim — body excluded."""

    priority_label = serializers.SerializerMethodField()
    reporter_username = serializers.SerializerMethodField()
    target_owner_username = serializers.SerializerMethodField()

    class Meta:
        model = Report
        fields = (
            "id",
            "target_type",
            "target_id",
            "reason",
            "priority",
            "priority_label",
            "status",
            "reporter_username",
            "target_owner_username",
            "created_at",
        )

    def get_priority_label(self, obj: Report) -> str:
        return obj.get_priority_display()

    def get_reporter_username(self, obj: Report) -> str:
        return getattr(obj.reporter, "username", "") or ""

    def get_target_owner_username(self, obj: Report) -> str:
        return getattr(obj.target_owner, "username", "") or ""


class ReportDetailSerializer(serializers.ModelSerializer):
    """Full report record for the admin detail panel."""

    priority_label = serializers.SerializerMethodField()
    status_label = serializers.SerializerMethodField()
    reason_label = serializers.SerializerMethodField()
    reporter_username = serializers.SerializerMethodField()
    target_owner_username = serializers.SerializerMethodField()

    class Meta:
        model = Report
        fields = (
            "id",
            "target_type",
            "target_id",
            "reason",
            "reason_label",
            "description",
            "evidence_url",
            "priority",
            "priority_label",
            "status",
            "status_label",
            "reporter",
            "reporter_username",
            "target_owner",
            "target_owner_username",
            "actioned_by",
            "actioned_at",
            "created_at",
        )

    def get_priority_label(self, obj: Report) -> str:
        return obj.get_priority_display()

    def get_status_label(self, obj: Report) -> str:
        return obj.get_status_display()

    def get_reason_label(self, obj: Report) -> str:
        return obj.get_reason_display()

    def get_reporter_username(self, obj: Report) -> str:
        return getattr(obj.reporter, "username", "") or ""

    def get_target_owner_username(self, obj: Report) -> str:
        return getattr(obj.target_owner, "username", "") or ""


class TriageInputSerializer(serializers.Serializer):
    """PATCH payload to triage a report."""

    status = serializers.ChoiceField(choices=ReportStatus.choices)
    note = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=1000,
    )


class BanUserInputSerializer(serializers.Serializer):
    """PATCH payload to ban a user."""

    reason = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=500,
    )
    days = serializers.IntegerField(
        required=False, allow_null=True, default=None, min_value=1, max_value=3650,
        help_text="Null = permanent. Otherwise ban length in days.",
    )


class BannedUserSerializer(serializers.ModelSerializer):
    """One row for the BannedUser admin list."""

    username = serializers.SerializerMethodField()
    banned_by_username = serializers.SerializerMethodField()

    class Meta:
        model = BannedUser
        fields = (
            "id",
            "user",
            "username",
            "banned_by",
            "banned_by_username",
            "reason",
            "banned_until",
            "created_at",
        )

    def get_username(self, obj: BannedUser) -> str:
        return getattr(obj.user, "username", "") or ""

    def get_banned_by_username(self, obj: BannedUser) -> str:
        return getattr(obj.banned_by, "username", "") or ""


class ModerationLogSerializer(serializers.ModelSerializer):
    """One row of the audit log."""

    actor_username = serializers.SerializerMethodField()

    class Meta:
        model = ModerationLog
        fields = (
            "id",
            "actor",
            "actor_username",
            "action",
            "target_type",
            "target_id",
            "before",
            "after",
            "note",
            "created_at",
        )

    def get_actor_username(self, obj: ModerationLog) -> str:
        return getattr(obj.actor, "username", "") or ""
