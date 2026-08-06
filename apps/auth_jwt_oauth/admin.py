"""Admin for the optional ``UserProfile`` row.

Falls back gracefully to stock ``admin.ModelAdmin`` when django-unfold
is not installed (same pattern as ``legal_cms_pages``).
"""
from __future__ import annotations

from django.contrib import admin

try:
    from unfold.admin import ModelAdmin as BaseModelAdmin
except ImportError:  # pragma: no cover — optional dependency
    BaseModelAdmin = admin.ModelAdmin  # type: ignore[misc,assignment]

from .models import UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(BaseModelAdmin):
    list_display = (
        "user", "display_name", "phone_e164", "phone_verified",
        "is_banned", "terms_accepted_at",
    )
    list_filter = ("is_banned", "phone_verified")
    search_fields = ("user__email", "display_name", "phone_e164")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("user",)
    fieldsets = (
        (None, {
            "fields": ("user", "display_name"),
        }),
        ("Téléphone", {
            "fields": ("phone_e164", "phone_verified"),
        }),
        ("Modération + légal", {
            "fields": ("is_banned", "terms_accepted_at"),
        }),
        ("Metadata", {
            "fields": ("created_at", "updated_at"),
        }),
    )
