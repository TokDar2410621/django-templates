from django.contrib import admin

from .models import VoiceMessage

try:
    from unfold.admin import ModelAdmin as BaseAdmin
except ImportError:
    BaseAdmin = admin.ModelAdmin


@admin.register(VoiceMessage)
class VoiceMessageAdmin(BaseAdmin):
    list_display = ("uuid", "sender", "duration_seconds", "size_bytes", "mime_type", "ref", "created_at")
    list_filter = ("mime_type", "created_at")
    search_fields = ("uuid", "sender__username", "ref")
    raw_id_fields = ("sender",)
