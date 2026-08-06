"""Admin for Partners, PartnerProductShares, Payouts, Affiliates.

CAD-friendly: a synthetic ``flat_per_order_cad`` readonly field renders
the cents column in dollars so non-technical operators don't have to
do mental math (note from MEMORY.md: "Admin must be non-technical-
friendly — Camille n'est pas tech").

Payouts are read-only by default — the table is an append-only ledger.
A "Retry payout" action lets the operator re-fire a FAILED row without
touching the data manually.

Falls back to ``django.contrib.admin.ModelAdmin`` if django-unfold
isn't installed.
"""
from __future__ import annotations

import logging

from django.contrib import admin, messages
from django.utils.html import format_html

try:
    from unfold.admin import ModelAdmin as BaseModelAdmin
except ImportError:  # pragma: no cover - optional dependency
    BaseModelAdmin = admin.ModelAdmin  # type: ignore[misc,assignment]

from .models import Affiliate, Partner, PartnerProductShare, Payout
from .services import (
    PartnerNotPayable,
    StripeNotConfigured,
    create_payout,
)

logger = logging.getLogger(__name__)


def _cents_to_money(cents: int, currency: str = "CAD") -> str:
    return f"{(cents or 0) / 100:,.2f} {currency}"


# ---------------------------------------------------------------------------
# Partner
# ---------------------------------------------------------------------------

class PartnerProductShareInline(admin.TabularInline):
    model = PartnerProductShare
    extra = 0
    fields = ("external_product_id", "share_bps", "notes")


@admin.register(Partner)
class PartnerAdmin(BaseModelAdmin):
    list_display = (
        "display_name",
        "user",
        "share_display",
        "flat_per_order_cad",
        "connect_badge",
        "active",
        "created_at",
    )
    list_filter = ("active", "stripe_account_verified")
    search_fields = (
        "display_name",
        "user__email",
        "user__username",
        "stripe_account_id",
        "payout_email",
    )
    autocomplete_fields = ("user",)
    readonly_fields = (
        "stripe_account_id",
        "stripe_account_verified",
        "created_at",
        "share_display",
        "flat_per_order_cad",
    )
    fieldsets = (
        (None, {
            "fields": ("user", "display_name", "payout_email", "active"),
        }),
        ("Compensation", {
            "fields": (
                "default_share_bps",
                "share_display",
                "flat_per_order_cents",
                "flat_per_order_cad",
            ),
            "description": (
                "Share is in <b>basis points</b>: 7000 = 70.00%, 10000 = "
                "100%. The flat fee (in cents) is deducted BEFORE the "
                "share kicks in. Set it to 0 if you don't deduct cost of "
                "goods."
            ),
        }),
        ("Stripe Connect", {
            "fields": ("stripe_account_id", "stripe_account_verified"),
            "description": (
                "Filled automatically when the partner completes the "
                "OAuth flow. Verified flips to True once Stripe confirms "
                "the account can receive transfers."
            ),
        }),
        ("Metadata", {
            "fields": ("notes", "created_at"),
        }),
    )
    inlines = (PartnerProductShareInline,)

    @admin.display(description="Share")
    def share_display(self, obj: Partner) -> str:
        return f"{obj.share_percent:.2f}%"

    @admin.display(description="Flat fee (per item)")
    def flat_per_order_cad(self, obj: Partner) -> str:
        return _cents_to_money(obj.flat_per_order_cents)

    @admin.display(description="Connect")
    def connect_badge(self, obj: Partner) -> str:
        if not obj.stripe_account_id:
            return format_html(
                '<span style="color:#888;">— not connected</span>'
            )
        if obj.stripe_account_verified:
            return format_html(
                '<span style="color:#0a0;">&#x2713; verified</span>'
            )
        return format_html(
            '<span style="color:#c80;">pending verification</span>'
        )


@admin.register(PartnerProductShare)
class PartnerProductShareAdmin(BaseModelAdmin):
    list_display = ("partner", "external_product_id", "share_display", "created_at")
    list_filter = ("partner",)
    search_fields = ("external_product_id", "partner__display_name")
    autocomplete_fields = ("partner",)

    @admin.display(description="Share")
    def share_display(self, obj: PartnerProductShare) -> str:
        return f"{obj.share_bps / 100:.2f}%"


# ---------------------------------------------------------------------------
# Payout
# ---------------------------------------------------------------------------

@admin.action(description="Retry payout (re-fire Stripe Transfer)")
def retry_failed_payouts(modeladmin, request, queryset):
    """Manual retry — only acts on FAILED rows."""
    n_ok = 0
    n_skip = 0
    n_err = 0
    for payout in queryset.select_related("partner"):
        if payout.status != Payout.STATUS_FAILED:
            n_skip += 1
            continue
        try:
            create_payout(
                partner=payout.partner,
                external_order_id=payout.external_order_id,
                external_order_item_id=payout.external_order_item_id,
                gross_cents=payout.gross_cents,
                share_bps_override=payout.share_bps,
                currency=payout.currency,
            )
            n_ok += 1
        except (PartnerNotPayable, StripeNotConfigured) as exc:
            logger.warning(
                "scm.admin.retry_failed payout=%s reason=%s",
                payout.pk, exc,
            )
            n_err += 1
    if n_ok:
        messages.success(request, f"{n_ok} payout(s) retried.")
    if n_skip:
        messages.info(request, f"{n_skip} row(s) skipped (not failed).")
    if n_err:
        messages.error(request, f"{n_err} row(s) errored — see logs.")


@admin.register(Payout)
class PayoutAdmin(BaseModelAdmin):
    list_display = (
        "id",
        "partner",
        "amount_display",
        "status",
        "external_order_id",
        "stripe_transfer_id",
        "created_at",
    )
    list_filter = ("status", "currency", "partner")
    search_fields = (
        "external_order_id",
        "external_order_item_id",
        "stripe_transfer_id",
        "partner__display_name",
    )
    autocomplete_fields = ("partner",)
    actions = (retry_failed_payouts,)

    # Ledger is append-only — every field is read-only from the admin.
    # Operator can still change ``status`` via actions, never directly.
    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

    @admin.display(description="Amount")
    def amount_display(self, obj: Payout) -> str:
        return _cents_to_money(obj.partner_amount_cents, obj.currency)


# ---------------------------------------------------------------------------
# Affiliate (optional)
# ---------------------------------------------------------------------------

@admin.register(Affiliate)
class AffiliateAdmin(BaseModelAdmin):
    list_display = (
        "code",
        "user",
        "commission_display",
        "flat_per_order_cad",
        "active",
        "created_at",
    )
    list_filter = ("active", "stripe_account_verified")
    search_fields = ("code", "user__email")
    autocomplete_fields = ("user",)
    readonly_fields = ("stripe_account_id", "stripe_account_verified", "created_at")

    @admin.display(description="Commission")
    def commission_display(self, obj: Affiliate) -> str:
        return f"{obj.commission_bps / 100:.2f}%"

    @admin.display(description="Flat (per order)")
    def flat_per_order_cad(self, obj: Affiliate) -> str:
        return _cents_to_money(obj.flat_per_order_cents)
