"""Admin for legal documents.

Workflow:
  1. Click "Add legal document"
  2. Pick kind + language, paste the markdown body, set effective_from
  3. Save as ``is_active=False`` (draft)
  4. Select the row + run "Publish this version" action — it atomically
     deactivates the previous active version and activates this one.

Never check ``is_active`` manually — use the action.

This module tries to use ``unfold.admin.ModelAdmin`` if django-unfold is
installed; otherwise it falls back to the stock ``admin.ModelAdmin``.
"""
from __future__ import annotations

from django import forms
from django.contrib import admin, messages
from django.utils.html import format_html

try:
    from unfold.admin import ModelAdmin as BaseModelAdmin
except ImportError:  # pragma: no cover - optional dependency
    BaseModelAdmin = admin.ModelAdmin  # type: ignore[misc,assignment]

from .models import LegalDocument
from .services import publish_document, render_html


class LegalDocumentForm(forms.ModelForm):
    class Meta:
        model = LegalDocument
        fields = "__all__"
        widgets = {
            "body_markdown": forms.Textarea(attrs={
                "rows": 30,
                "cols": 100,
                "style": "font-family: monospace; width: 100%;",
            }),
        }


@admin.action(description="Publish this version (deactivates previous)")
def publish_selected(modeladmin, request, queryset):
    n = 0
    skipped = 0
    for doc in queryset:
        if doc.is_active:
            skipped += 1
            continue
        publish_document(
            kind=doc.kind,
            language=doc.language,
            title=doc.title,
            body_markdown=doc.body_markdown,
            effective_from=doc.effective_from,
            created_by=request.user if request.user.is_authenticated else None,
        )
        # Drop the draft row — the new active row carries the same content.
        doc.delete()
        n += 1
    if n:
        messages.success(request, f"{n} document(s) published.")
    if skipped:
        messages.warning(
            request,
            f"{skipped} row(s) already active — skipped.",
        )


@admin.register(LegalDocument)
class LegalDocumentAdmin(BaseModelAdmin):
    form = LegalDocumentForm
    list_display = (
        "kind", "language", "title", "is_active",
        "effective_from", "created_at",
    )
    list_filter = ("kind", "language", "is_active")
    search_fields = ("title", "body_markdown")
    readonly_fields = ("is_active", "created_at", "updated_at", "preview_html")
    fieldsets = (
        (None, {
            "fields": ("kind", "language", "title", "effective_from"),
        }),
        ("Markdown content", {
            "fields": ("body_markdown", "preview_html"),
        }),
        ("Metadata", {
            "fields": ("is_active", "created_by", "created_at", "updated_at"),
        }),
    )
    actions = (publish_selected,)
    ordering = ("kind", "language", "-effective_from")

    @admin.display(description="HTML preview (read-only)")
    def preview_html(self, obj):
        if not obj or not obj.pk:
            return "Save the version to see the rendered output."
        return format_html(
            '<div style="border:1px solid #ccc; padding:1em; '
            'max-width:800px; background:#fff; color:#000;">{}</div>',
            format_html(render_html(obj.body_markdown)),
        )
