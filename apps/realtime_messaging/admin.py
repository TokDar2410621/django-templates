from django.contrib import admin

from .models import Block

try:
    from unfold.admin import ModelAdmin as BaseAdmin
except ImportError:
    BaseAdmin = admin.ModelAdmin


@admin.register(Block)
class BlockAdmin(BaseAdmin):
    list_display = ("id", "blocker", "blocked", "reason", "created_at")
    list_filter = ("created_at",)
    search_fields = ("blocker__username", "blocked__username", "reason")
    raw_id_fields = ("blocker", "blocked")
