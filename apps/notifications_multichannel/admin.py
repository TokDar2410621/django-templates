"""Admin for push subscriptions + delivery logs.

Tries to use ``unfold.admin.ModelAdmin`` if django-unfold is installed;
otherwise falls back to the stock ``admin.ModelAdmin``.
"""
from __future__ import annotations

from django.contrib import admin

try:
    from unfold.admin import ModelAdmin as BaseModelAdmin
except ImportError:  # pragma: no cover — optional dependency
    BaseModelAdmin = admin.ModelAdmin  # type: ignore[misc,assignment]

from .models import NotificationLog, PushSubscription


@admin.register(PushSubscription)
class PushSubscriptionAdmin(BaseModelAdmin):
    list_display = ("user", "user_agent_short", "created_at", "last_used_at")
    list_filter = ("created_at",)
    search_fields = ("user__email", "user__username", "user_agent", "endpoint")
    readonly_fields = (
        "endpoint", "p256dh", "auth", "user_agent",
        "created_at", "last_used_at",
    )
    ordering = ("-created_at",)

    @admin.display(description="User agent")
    def user_agent_short(self, obj: PushSubscription) -> str:
        return (obj.user_agent or "")[:60]


@admin.register(NotificationLog)
class NotificationLogAdmin(BaseModelAdmin):
    list_display = (
        "created_at", "channel", "status", "user",
        "subject_short", "target_short",
    )
    list_filter = ("channel", "status", "created_at")
    search_fields = (
        "user__email", "user__username",
        "subject", "target", "provider_message_id", "error",
    )
    readonly_fields = (
        "user", "channel", "status",
        "subject", "target", "provider_message_id", "error",
        "created_at",
    )
    ordering = ("-created_at",)

    def has_add_permission(self, request) -> bool:
        return False  # logs are created by the service layer only

    @admin.display(description="Subject")
    def subject_short(self, obj: NotificationLog) -> str:
        return (obj.subject or "")[:60]

    @admin.display(description="Target")
    def target_short(self, obj: NotificationLog) -> str:
        return (obj.target or "")[:60]
