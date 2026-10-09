"""Admin des appareils push.

Utilise ``unfold.admin.ModelAdmin`` si django-unfold est installe, sinon
``admin.ModelAdmin``.
"""
from __future__ import annotations

from django.contrib import admin

try:
    from unfold.admin import ModelAdmin as BaseModelAdmin
except ImportError:  # pragma: no cover : dependance optionnelle
    BaseModelAdmin = admin.ModelAdmin  # type: ignore[misc,assignment]

from .models import PushDevice


@admin.register(PushDevice)
class PushDeviceAdmin(BaseModelAdmin):
    list_display = ("id", "user", "kind", "apns_sandbox", "last_used_at", "last_error", "created_at")
    list_filter = ("kind", "apns_sandbox")
    search_fields = ("last_error",)
    raw_id_fields = ("user",)
    readonly_fields = ("token_hash", "created_at", "last_used_at")
