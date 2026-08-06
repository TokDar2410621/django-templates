"""Admin for Report / BannedUser / ModerationLog.

Workflows:

  ReportAdmin:
    - Bulk actions: "Mark actioned", "Dismiss", "Ban target_owner"
    - Priority badge in list_display (color-coded)
    - Triaging through the actions writes ModerationLog rows (via services)

  BannedUserAdmin:
    - Bulk "Unban" action — clears ``User.is_banned`` if present, deletes
      the BannedUser row, writes a ModerationLog row.

  ModerationLogAdmin:
    - Read-only (``has_add_permission=False``). Logs are append-only and
      must be written through ``services.log_action`` so before/after
      snapshots are captured correctly.

Tries ``unfold.admin.ModelAdmin`` first; falls back to stock
``admin.ModelAdmin`` if Unfold isn't installed.
"""
from __future__ import annotations

from django.contrib import admin, messages
from django.utils.html import format_html

try:
    from unfold.admin import ModelAdmin as BaseModelAdmin
except ImportError:  # pragma: no cover - optional dependency
    BaseModelAdmin = admin.ModelAdmin  # type: ignore[misc,assignment]

from .models import BannedUser, ModerationLog, Report, ReportPriority, ReportStatus
from .services import ban_user, triage_report, unban_user


_PRIORITY_PALETTE = {
    int(ReportPriority.URGENT): ("Urgent", "#dc2626"),
    int(ReportPriority.HIGH):   ("High",   "#f97316"),
    int(ReportPriority.MEDIUM): ("Medium", "#6c48e8"),
    int(ReportPriority.LOW):    ("Low",    "#6b608f"),
}


@admin.register(Report)
class ReportAdmin(BaseModelAdmin):
    list_display = (
        "priority_badge",
        "id",
        "target_type",
        "target_id_short",
        "reason",
        "status",
        "reporter",
        "target_owner",
        "created_at",
    )
    list_filter = ("priority", "status", "target_type", "reason", "created_at")
    search_fields = ("target_id", "description", "reporter__username", "target_owner__username")
    readonly_fields = ("created_at", "actioned_at", "actioned_by")
    actions = ("mark_actioned", "dismiss_reports", "ban_target_owner")
    ordering = ("-priority", "-created_at")

    @admin.display(description="priority", ordering="-priority")
    def priority_badge(self, obj):
        label, color = _PRIORITY_PALETTE.get(obj.priority, ("?", "#6b608f"))
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:999px;font-size:11px;font-weight:600;">{}</span>',
            color, label,
        )

    @admin.display(description="target")
    def target_id_short(self, obj):
        if len(obj.target_id) <= 16:
            return obj.target_id
        return obj.target_id[:14] + "…"

    @admin.action(description="Mark selected as ACTIONED (writes audit log)")
    def mark_actioned(self, request, queryset):
        n = 0
        for report in queryset:
            triage_report(
                report=report,
                actor=request.user,
                status=ReportStatus.ACTIONED,
                note="Bulk action via admin",
            )
            n += 1
        self.message_user(request, f"{n} report(s) marked actioned.", messages.SUCCESS)

    @admin.action(description="Dismiss selected (writes audit log)")
    def dismiss_reports(self, request, queryset):
        n = 0
        for report in queryset:
            triage_report(
                report=report,
                actor=request.user,
                status=ReportStatus.DISMISSED,
                note="Bulk dismiss via admin",
            )
            n += 1
        self.message_user(request, f"{n} report(s) dismissed.", messages.SUCCESS)

    @admin.action(description="Ban target_owner (permanent) and mark report actioned")
    def ban_target_owner(self, request, queryset):
        banned = 0
        skipped = 0
        for report in queryset:
            owner = report.target_owner
            if owner is None or getattr(owner, "is_staff", False):
                skipped += 1
                continue
            ban_user(user=owner, by=request.user, reason=f"Report #{report.pk}")
            triage_report(
                report=report,
                actor=request.user,
                status=ReportStatus.ACTIONED,
                note=f"Ban via admin (report {report.pk})",
            )
            banned += 1
        if banned:
            self.message_user(request, f"{banned} user(s) banned.", messages.SUCCESS)
        if skipped:
            self.message_user(
                request,
                f"{skipped} report(s) skipped (no target_owner or staff user).",
                messages.WARNING,
            )


@admin.register(BannedUser)
class BannedUserAdmin(BaseModelAdmin):
    list_display = ("user", "banned_by", "reason_short", "banned_until", "created_at")
    list_filter = ("created_at", "banned_until")
    search_fields = ("user__username", "user__email", "reason")
    readonly_fields = ("created_at",)
    actions = ("unban_action",)

    @admin.display(description="reason")
    def reason_short(self, obj):
        return (obj.reason[:60] + "…") if len(obj.reason or "") > 60 else (obj.reason or "")

    @admin.action(description="Unban selected (writes audit log)")
    def unban_action(self, request, queryset):
        n = 0
        # Snapshot users before we delete the rows
        users = [ban.user for ban in queryset.select_related("user")]
        for user in users:
            unban_user(user=user, by=request.user, note="Bulk unban via admin")
            n += 1
        self.message_user(request, f"{n} user(s) unbanned.", messages.SUCCESS)


@admin.register(ModerationLog)
class ModerationLogAdmin(BaseModelAdmin):
    list_display = ("created_at", "actor", "action", "target_type", "target_id_short", "note_short")
    list_filter = ("action", "target_type", "created_at")
    search_fields = ("target_id", "note", "actor__username", "action")
    readonly_fields = (
        "actor", "action", "target_type", "target_id",
        "before", "after", "note", "created_at",
    )
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False  # logs are append-only via services.log_action()

    def has_change_permission(self, request, obj=None):
        return False  # logs are immutable

    def has_delete_permission(self, request, obj=None):
        return False  # logs survive everything

    @admin.display(description="target")
    def target_id_short(self, obj):
        if len(obj.target_id) <= 16:
            return obj.target_id
        return obj.target_id[:14] + "…"

    @admin.display(description="note")
    def note_short(self, obj):
        return (obj.note[:80] + "…") if len(obj.note or "") > 80 else (obj.note or "")
