"""Admin for ApiToken.

Operators can audit which tokens exist, when they were last used, and
revoke them via a bulk action. The plain token is NEVER exposed here —
it doesn't exist in the DB to begin with. ``key_hash`` is shown as a
read-only field for forensic purposes ("this hash matches a token we
saw in nginx logs").

Tries django-unfold first; falls back to stock ``ModelAdmin``.
"""
from __future__ import annotations

from django.contrib import admin, messages
from django.utils import timezone

try:
    from unfold.admin import ModelAdmin as BaseModelAdmin
except ImportError:  # pragma: no cover - optional dependency
    BaseModelAdmin = admin.ModelAdmin  # type: ignore[misc,assignment]

from .models import ApiToken


@admin.action(description="Revoke selected tokens")
def revoke_selected(modeladmin, request, queryset):
    now = timezone.now()
    n = queryset.filter(revoked_at__isnull=True).update(revoked_at=now)
    if n:
        messages.success(request, f"{n} token(s) revoked.")
    else:
        messages.info(request, "No active tokens in the selection.")


@admin.register(ApiToken)
class ApiTokenAdmin(BaseModelAdmin):
    list_display = (
        "name",
        "user",
        "key_prefix",
        "is_active",
        "last_used_at",
        "revoked_at",
        "created_at",
    )
    list_filter = ("revoked_at",)
    search_fields = ("name", "user__username", "user__email", "key_prefix")
    readonly_fields = ("key_hash", "key_prefix", "created_at", "last_used_at")
    ordering = ("-created_at",)
    actions = (revoke_selected,)

    @admin.display(boolean=True, description="Active", ordering="revoked_at")
    def is_active(self, obj: ApiToken) -> bool:
        return obj.revoked_at is None
