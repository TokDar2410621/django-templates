"""Django admin for conversational_ai_engine.

Inherits from ``unfold.admin.ModelAdmin`` if django-unfold is installed;
falls back to the stock admin otherwise (same pattern as legal_cms_pages).

The Generation admin is intentionally read-only — operators can browse the
audit trail but not edit it. Persona and PromptTemplate are editable so
support can adjust a user's setup without leaving the admin.
"""
from __future__ import annotations

from django.contrib import admin

try:
    from unfold.admin import ModelAdmin as BaseModelAdmin
except ImportError:  # pragma: no cover - optional dependency
    BaseModelAdmin = admin.ModelAdmin  # type: ignore[misc,assignment]

from .models import Generation, PersonaContext, PromptTemplate


@admin.register(PersonaContext)
class PersonaContextAdmin(BaseModelAdmin):
    list_display = ("user", "role", "industry", "updated_at")
    list_select_related = ("user",)
    search_fields = (
        "user__username", "user__email",
        "role", "industry", "expertise",
    )
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("user", "role", "industry")}),
        ("Voice", {"fields": ("writing_style", "bio", "examples")}),
        ("Extra context", {"fields": ("expertise", "target_audience", "additional_context")}),
        ("Metadata", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(PromptTemplate)
class PromptTemplateAdmin(BaseModelAdmin):
    list_display = ("name", "user", "default_tone", "is_default", "updated_at")
    list_filter = ("default_tone", "is_default")
    list_select_related = ("user",)
    search_fields = ("name", "description", "user__username", "user__email")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("user", "name", "description", "is_default")}),
        ("Wrapper", {"fields": ("default_tone", "prompt_prefix", "prompt_suffix")}),
        ("Metadata", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(Generation)
class GenerationAdmin(BaseModelAdmin):
    list_display = (
        "id", "user", "tone", "provider", "model",
        "input_tokens", "output_tokens", "cost_usd", "created_at",
    )
    list_filter = ("provider", "tone", "model")
    list_select_related = ("user", "template")
    search_fields = (
        "user__username", "user__email", "session_key",
        "input_text", "output_text",
    )
    readonly_fields = tuple(
        f.name for f in Generation._meta.fields
    ) + ("metadata", "retrieved_memory_ids")
    fieldsets = (
        (None, {"fields": ("user", "session_key", "template", "tone")}),
        ("Content", {"fields": ("input_text", "output_text")}),
        ("Accounting", {"fields": (
            "provider", "model",
            "input_tokens", "output_tokens", "cost_usd",
        )}),
        ("RAG", {"fields": ("retrieved_memory_ids",)}),
        ("Metadata", {"fields": ("metadata", "created_at")}),
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        # View-only; operators can browse but not edit.
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return request.user.is_superuser
