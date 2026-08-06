"""Admin for the newsletter engine.

The admin is the operator's daily workspace — every model is registered with
helpful list_display columns, filters, search, and useful actions:

- CampaignAdmin       — "Send now", "Schedule", "Cancel", "Duplicate", "Preview HTML"
- SubscriberAdmin     — "Unsubscribe selected", "Tag selected", "Export CSV", "Add to list"
- AutomationAdmin     — inline AutomationStep
- SegmentAdmin        — read-only compiled_count (populated on save)
- DeliveryAdmin       — read-only (audit)
- BounceEventAdmin    — read-only (audit)

This module tries to use ``unfold.admin.ModelAdmin`` if django-unfold is
installed; otherwise it falls back to stock ``admin.ModelAdmin``.
"""
from __future__ import annotations

import csv
import logging

from django.contrib import admin, messages
from django.http import HttpResponse
from django.utils import timezone
from django.utils.html import format_html

try:
    from unfold.admin import ModelAdmin as BaseModelAdmin
    from unfold.admin import TabularInline as BaseTabularInline
except ImportError:  # pragma: no cover - optional dependency
    BaseModelAdmin = admin.ModelAdmin  # type: ignore[misc,assignment]
    BaseTabularInline = admin.TabularInline  # type: ignore[misc,assignment]

from .models import (
    Automation,
    AutomationEnrollment,
    AutomationStep,
    BounceEvent,
    Campaign,
    Delivery,
    LinkClick,
    MailingList,
    Membership,
    Segment,
    Subscriber,
    SubscriberTag,
    Tag,
    UnsubscribeToken,
)
from .services.campaigns import cancel_campaign, create_campaign, send_campaign
from .services.subscribers import (
    add_to_list as svc_add_to_list,
    tag_subscriber as svc_tag_subscriber,
    unsubscribe as svc_unsubscribe,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Subscriber
# ---------------------------------------------------------------------------
@admin.register(Subscriber)
class SubscriberAdmin(BaseModelAdmin):
    list_display = (
        "email", "name", "status", "consented_marketing",
        "bounce_count", "source", "created_at",
    )
    list_filter = ("status", "consented_marketing", "locale", "source")
    search_fields = ("email", "name")
    readonly_fields = (
        "status", "confirmed_at", "unsubscribed_at",
        "bounce_count", "last_bounce_at", "created_at", "updated_at",
    )
    autocomplete_fields = ("tenant",)
    date_hierarchy = "created_at"
    actions = ("unsubscribe_selected", "export_csv")

    fieldsets = (
        ("Identity", {"fields": ("tenant", "email", "name", "locale", "source")}),
        ("Consent (Loi 25 / RGPD)", {"fields": ("consented_marketing",)}),
        ("Status", {
            "fields": ("status", "confirmed_at", "unsubscribed_at"),
        }),
        ("Bounces", {"fields": ("bounce_count", "last_bounce_at")}),
        ("Metadata", {"fields": ("metadata", "created_at", "updated_at")}),
    )

    @admin.action(description="Unsubscribe selected (all lists)")
    def unsubscribe_selected(self, request, queryset):
        n = 0
        for sub in queryset:
            if sub.status not in (Subscriber.STATUS_UNSUBSCRIBED, Subscriber.STATUS_BOUNCED, Subscriber.STATUS_COMPLAINED):
                sub.status = Subscriber.STATUS_UNSUBSCRIBED
                sub.unsubscribed_at = timezone.now()
                sub.save(update_fields=["status", "unsubscribed_at", "updated_at"])
                n += 1
        self.message_user(request, f"Unsubscribed {n} subscriber(s).", messages.SUCCESS)

    @admin.action(description="Export selected to CSV")
    def export_csv(self, request, queryset):
        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = (
            f'attachment; filename="subscribers_{timezone.now():%Y%m%d}.csv"'
        )
        writer = csv.writer(resp)
        writer.writerow([
            "id", "email", "name", "status", "locale",
            "consented_marketing", "source", "bounce_count", "created_at",
        ])
        for s in queryset:
            writer.writerow([
                s.pk, s.email, s.name, s.status, s.locale,
                s.consented_marketing, s.source, s.bounce_count, s.created_at,
            ])
        return resp


# ---------------------------------------------------------------------------
# Mailing list + membership
# ---------------------------------------------------------------------------
class MembershipInline(BaseTabularInline):
    model = Membership
    extra = 0
    fk_name = "list"
    fields = ("subscriber", "status", "subscribed_at", "unsubscribed_at")
    readonly_fields = ("subscribed_at", "unsubscribed_at")
    autocomplete_fields = ("subscriber",)


@admin.register(MailingList)
class MailingListAdmin(BaseModelAdmin):
    list_display = (
        "name", "slug", "is_active", "requires_double_opt_in",
        "default_from_role", "created_at",
    )
    list_filter = ("is_active", "requires_double_opt_in")
    search_fields = ("name", "slug", "description")
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("tenant",)


# ---------------------------------------------------------------------------
# Tag
# ---------------------------------------------------------------------------
@admin.register(Tag)
class TagAdmin(BaseModelAdmin):
    list_display = ("name", "tenant", "created_at")
    search_fields = ("name",)
    autocomplete_fields = ("tenant",)


@admin.register(SubscriberTag)
class SubscriberTagAdmin(BaseModelAdmin):
    list_display = ("subscriber", "tag", "created_at")
    search_fields = ("subscriber__email", "tag__name")
    autocomplete_fields = ("subscriber", "tag")


# ---------------------------------------------------------------------------
# Segment
# ---------------------------------------------------------------------------
@admin.register(Segment)
class SegmentAdmin(BaseModelAdmin):
    list_display = ("name", "list", "subscriber_count", "last_evaluated_at", "updated_at")
    list_filter = ("list",)
    search_fields = ("name",)
    readonly_fields = ("subscriber_count", "last_evaluated_at", "created_at", "updated_at")
    autocomplete_fields = ("tenant", "list")


# ---------------------------------------------------------------------------
# Campaign + actions
# ---------------------------------------------------------------------------
@admin.register(Campaign)
class CampaignAdmin(BaseModelAdmin):
    list_display = (
        "subject", "status", "target_label", "sent_count",
        "open_count", "click_count", "scheduled_at", "sent_at",
    )
    list_filter = ("status", "list")
    search_fields = ("subject",)
    readonly_fields = (
        "status", "sent_at", "created_by", "created_at",
        "sent_count", "delivered_count", "open_count", "click_count",
        "bounce_count", "unsubscribe_count", "complaint_count",
        "preview_html",
    )
    autocomplete_fields = ("tenant", "list", "segment", "created_by")
    actions = ("send_now", "cancel_selected", "duplicate_selected")

    fieldsets = (
        ("Targeting", {"fields": ("tenant", "list", "segment")}),
        ("Content", {"fields": ("subject", "html_body", "text_body", "preview_html")}),
        ("Sender", {
            "fields": ("from_role", "from_email_override", "reply_to"),
        }),
        ("Scheduling", {"fields": ("scheduled_at", "status", "sent_at")}),
        ("Stats (live)", {
            "fields": (
                "sent_count", "delivered_count", "open_count", "click_count",
                "bounce_count", "unsubscribe_count", "complaint_count",
            ),
        }),
        ("Metadata", {"fields": ("created_by", "created_at")}),
    )

    @admin.display(description="Target")
    def target_label(self, obj: Campaign) -> str:
        if obj.list_id:
            return f"list: {obj.list.slug}"
        if obj.segment_id:
            return f"segment: {obj.segment.name}"
        return "—"

    @admin.display(description="HTML preview (read-only)")
    def preview_html(self, obj: Campaign) -> str:
        if not obj or not obj.pk:
            return "Save the campaign to see the preview."
        return format_html(
            '<div style="border:1px solid #ccc; padding:1em; '
            'max-width:800px; background:#fff; color:#000;">{}</div>',
            format_html(obj.html_body or ""),
        )

    @admin.action(description="Send selected campaigns now")
    def send_now(self, request, queryset):
        n = 0
        for camp in queryset:
            try:
                send_campaign(camp)
                n += 1
            except Exception as exc:
                self.message_user(
                    request, f"Failed to send #{camp.pk}: {exc}", messages.ERROR,
                )
        if n:
            self.message_user(request, f"Sent {n} campaign(s).", messages.SUCCESS)

    @admin.action(description="Cancel selected campaigns")
    def cancel_selected(self, request, queryset):
        n = 0
        for camp in queryset:
            cancel_campaign(camp, reason="admin action")
            n += 1
        self.message_user(request, f"Cancelled {n} campaign(s).", messages.SUCCESS)

    @admin.action(description="Duplicate selected as draft")
    def duplicate_selected(self, request, queryset):
        n = 0
        for camp in queryset:
            target = camp.list or camp.segment
            create_campaign(
                tenant=camp.tenant,
                target=target,
                subject=f"[copy] {camp.subject}",
                html_body=camp.html_body,
                text_body=camp.text_body,
                from_role=camp.from_role,
                from_email_override=camp.from_email_override,
                reply_to=camp.reply_to,
                created_by=request.user if request.user.is_authenticated else None,
            )
            n += 1
        self.message_user(request, f"Duplicated {n} campaign(s).", messages.SUCCESS)


# ---------------------------------------------------------------------------
# Delivery (read-only audit)
# ---------------------------------------------------------------------------
@admin.register(Delivery)
class DeliveryAdmin(BaseModelAdmin):
    list_display = (
        "id", "campaign", "subscriber", "status",
        "sent_at", "opened_at", "clicked_at", "bounced_at",
    )
    list_filter = ("status",)
    search_fields = ("subscriber__email", "campaign__subject", "provider_message_id")
    readonly_fields = tuple(f.name for f in Delivery._meta.fields)
    date_hierarchy = "sent_at"

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(LinkClick)
class LinkClickAdmin(BaseModelAdmin):
    list_display = ("delivery", "original_url", "clicked_at")
    search_fields = ("original_url",)
    date_hierarchy = "clicked_at"

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False


# ---------------------------------------------------------------------------
# Automation + step inline
# ---------------------------------------------------------------------------
class AutomationStepInline(BaseTabularInline):
    model = AutomationStep
    extra = 1
    fields = ("order", "delay_seconds", "subject", "html_body", "condition")


@admin.register(Automation)
class AutomationAdmin(BaseModelAdmin):
    list_display = ("name", "trigger", "is_active", "created_at")
    list_filter = ("trigger", "is_active")
    search_fields = ("name",)
    autocomplete_fields = ("tenant",)
    inlines = (AutomationStepInline,)


@admin.register(AutomationEnrollment)
class AutomationEnrollmentAdmin(BaseModelAdmin):
    list_display = (
        "subscriber", "automation", "last_step_index", "last_step_at",
        "completed_at", "cancelled_at",
    )
    list_filter = ("automation",)
    search_fields = ("subscriber__email", "automation__name")
    readonly_fields = tuple(f.name for f in AutomationEnrollment._meta.fields)
    date_hierarchy = "started_at"


# ---------------------------------------------------------------------------
# Unsubscribe tokens + bounces (audit)
# ---------------------------------------------------------------------------
@admin.register(UnsubscribeToken)
class UnsubscribeTokenAdmin(BaseModelAdmin):
    list_display = ("subscriber", "scope", "created_at", "used_at")
    list_filter = ("scope",)
    search_fields = ("subscriber__email", "token")
    readonly_fields = ("token", "created_at", "used_at")


@admin.register(BounceEvent)
class BounceEventAdmin(BaseModelAdmin):
    list_display = ("subscriber", "kind", "provider_message_id", "created_at")
    list_filter = ("kind",)
    search_fields = ("subscriber__email", "provider_message_id")
    readonly_fields = tuple(f.name for f in BounceEvent._meta.fields)
    date_hierarchy = "created_at"

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False
