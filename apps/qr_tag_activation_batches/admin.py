"""Admin for ActivationBatch, ActivationCode, OwnershipDispute.

The "Generate batch" workflow lives at the changelist level — clicking it
runs :func:`services.generate_batch` then redirects to a CSV download.

Falls back to stock ``admin.ModelAdmin`` if ``django-unfold`` isn't
installed (try/except import).
"""
from __future__ import annotations

from django import forms
from django.contrib import admin, messages
from django.http import HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path
from django.utils import timezone

try:
    from unfold.admin import ModelAdmin as BaseModelAdmin
except ImportError:  # pragma: no cover - optional dependency
    BaseModelAdmin = admin.ModelAdmin  # type: ignore[misc,assignment]

from .models import (
    ActivationBatch,
    ActivationCode,
    ClaimMode,
    ClaimStatus,
    OwnershipDispute,
    _batch_kinds,
    _tag_formats,
)
from .services import (
    BatchSizeError,
    bulk_export_csv,
    generate_batch,
)


# ---------------------------------------------------------------------------
# Batch generation form
# ---------------------------------------------------------------------------
class GenerateBatchForm(forms.Form):
    size = forms.IntegerField(min_value=1, max_value=10000)
    kind = forms.ChoiceField(choices=lambda: _batch_kinds())
    tag_format = forms.ChoiceField(choices=lambda: _tag_formats())
    claim_mode = forms.ChoiceField(
        choices=ClaimMode.choices,
        initial=ClaimMode.CODE,
        help_text=(
            "CODE = a card with a 6-digit code ships with each tag. "
            "PHOTO = no code; the first scanner + photo wins the tag "
            "(useful for supermarket / pre-printed factory tags)."
        ),
    )
    partner_label = forms.CharField(max_length=120, required=False)
    notes = forms.CharField(widget=forms.Textarea, required=False)


# ---------------------------------------------------------------------------
# ActivationBatch admin
# ---------------------------------------------------------------------------
@admin.register(ActivationBatch)
class ActivationBatchAdmin(BaseModelAdmin):
    list_display = (
        "id", "kind", "tag_format", "claim_mode", "size",
        "consumed_count", "partner_label", "created_by", "created_at",
    )
    list_filter = ("kind", "tag_format", "claim_mode")
    search_fields = ("partner_label", "notes")
    readonly_fields = ("size", "claim_mode", "created_at", "consumed_count")
    ordering = ("-created_at",)

    # Custom changelist template hook — projects can override to add a
    # "Generate batch" button. The template name matches the FIN extract.
    change_list_template = (
        "admin/qr_tag_activation_batches/activationbatch_change_list.html"
    )

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "generate/",
                self.admin_site.admin_view(self.generate_view),
                name="qr_tag_activation_batches_generate",
            ),
            path(
                "<int:batch_id>/export-csv/",
                self.admin_site.admin_view(self.export_csv_view),
                name="qr_tag_activation_batches_export_csv",
            ),
        ]
        return custom + urls

    # --- Generate ---------------------------------------------------------
    def generate_view(self, request):
        if request.method == "POST":
            form = GenerateBatchForm(request.POST)
            if form.is_valid():
                try:
                    batch = generate_batch(
                        size=form.cleaned_data["size"],
                        kind=form.cleaned_data["kind"],
                        tag_format=form.cleaned_data["tag_format"],
                        claim_mode=form.cleaned_data["claim_mode"],
                        partner_label=form.cleaned_data["partner_label"],
                        notes=form.cleaned_data["notes"],
                        created_by=(
                            request.user
                            if request.user.is_authenticated else None
                        ),
                    )
                except BatchSizeError as exc:
                    messages.error(request, str(exc))
                    return redirect(".")
                messages.success(
                    request,
                    f"Batch #{batch.pk} created with {batch.size} codes. "
                    "Download the CSV below.",
                )
                return redirect(f"../{batch.pk}/export-csv/")
        else:
            form = GenerateBatchForm()

        ctx = self.admin_site.each_context(request)
        ctx.update({"form": form, "title": "Generate an activation batch"})
        return TemplateResponse(
            request,
            "admin/qr_tag_activation_batches/generate_batch.html",
            ctx,
        )

    # --- CSV export -------------------------------------------------------
    def export_csv_view(self, request, batch_id):
        try:
            batch = ActivationBatch.objects.get(pk=batch_id)
        except ActivationBatch.DoesNotExist:
            messages.error(request, "Batch not found.")
            return redirect("..")
        csv_bytes = bulk_export_csv(batch.pk)
        resp = HttpResponse(csv_bytes, content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = (
            f'attachment; filename="activation-batch-{batch.pk}.csv"'
        )
        return resp


# ---------------------------------------------------------------------------
# ActivationCode admin (mostly read-only)
# ---------------------------------------------------------------------------
@admin.register(ActivationCode)
class ActivationCodeAdmin(BaseModelAdmin):
    list_display = (
        "qr_slug", "activation_code", "batch", "consumed_at",
        "consumed_by", "claim_status",
    )
    list_filter = (
        "batch__kind",
        "batch__tag_format",
        "batch__claim_mode",
        "claim_status",
        ("consumed_at", admin.EmptyFieldListFilter),
    )
    search_fields = ("qr_slug", "activation_code")
    readonly_fields = (
        "batch", "qr_slug", "activation_code",
        "consumed_at", "consumed_by",
        "claim_status", "provisional_until",
        "linked_object_type", "linked_object_id",
        "proof_photo",
    )
    ordering = ("-consumed_at",)


# ---------------------------------------------------------------------------
# OwnershipDispute admin — resolve / reject actions
# ---------------------------------------------------------------------------
@admin.action(description="Resolve IN FAVOR of the challenger (transfer ownership)")
def resolve_for_challenger(modeladmin, request, queryset):
    n = 0
    for d in queryset.select_related("code", "claimer"):
        if d.resolved_at is not None:
            continue
        code = d.code
        code.consumed_by = d.claimer
        code.claim_status = ClaimStatus.CONFIRMED
        code.provisional_until = None
        code.save(
            update_fields=["consumed_by", "claim_status", "provisional_until"],
        )
        d.resolved_at = timezone.now()
        d.resolved_in_favor_of_claimer = True
        d.resolved_by = request.user
        d.save(
            update_fields=[
                "resolved_at", "resolved_in_favor_of_claimer", "resolved_by",
            ],
        )
        n += 1
    messages.success(
        request, f"{n} dispute(s) accepted. Ownership transferred to challenger.",
    )


@admin.action(description="Reject (current owner keeps the tag)")
def reject_dispute(modeladmin, request, queryset):
    n = 0
    for d in queryset.select_related("code"):
        if d.resolved_at is not None:
            continue
        code = d.code
        if code.claim_status != ClaimStatus.CONFIRMED:
            code.claim_status = ClaimStatus.CONFIRMED
            code.provisional_until = None
            code.save(update_fields=["claim_status", "provisional_until"])
        d.resolved_at = timezone.now()
        d.resolved_in_favor_of_claimer = False
        d.resolved_by = request.user
        d.save(
            update_fields=[
                "resolved_at", "resolved_in_favor_of_claimer", "resolved_by",
            ],
        )
        n += 1
    messages.success(request, f"{n} dispute(s) rejected.")


@admin.register(OwnershipDispute)
class OwnershipDisputeAdmin(BaseModelAdmin):
    list_display = (
        "id", "code", "claimer", "is_resolved",
        "resolved_in_favor_of_claimer", "created_at",
    )
    list_filter = ("resolved_in_favor_of_claimer",)
    search_fields = ("code__qr_slug", "claimer__email", "claimer__username")
    readonly_fields = (
        "code", "claimer", "proof_photo", "claimer_message",
        "created_at", "resolved_at", "resolved_by",
    )
    actions = (resolve_for_challenger, reject_dispute)
    ordering = ("-created_at",)

    @admin.display(boolean=True, description="Resolved?")
    def is_resolved(self, obj):
        return obj.resolved_at is not None
