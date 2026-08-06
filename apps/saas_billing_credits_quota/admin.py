"""Admin for the billing subsystem.

CreditTransaction is read-only — the ledger is append-only. Edit a row only
in extraordinary circumstances and never through the admin (write a
management command that creates a 'refund' txn instead, so the audit trail
stays intact).

CreditBalance has a custom 'Add gift credits' action so support can hand out
free credits to a complaining customer without going through Stripe.

This module tries to use ``unfold.admin.ModelAdmin`` if django-unfold is
installed; otherwise it falls back to stock ``admin.ModelAdmin``.
"""
from __future__ import annotations

from django import forms
from django.contrib import admin, messages
from django.utils.html import format_html

try:
    from unfold.admin import ModelAdmin as BaseModelAdmin
except ImportError:  # pragma: no cover - optional dependency
    BaseModelAdmin = admin.ModelAdmin  # type: ignore[misc,assignment]

from .models import (
    CreditBalance,
    CreditTransaction,
    MonthlyQuota,
    Subscription,
)
from .selectors import ledger_sum
from .services import add_credits


# ---------------------------------------------------------------------------
# Subscription
# ---------------------------------------------------------------------------

@admin.register(Subscription)
class SubscriptionAdmin(BaseModelAdmin):
    list_display = (
        "user", "plan", "status", "is_paid_badge",
        "stripe_customer_id", "current_period_end", "updated_at",
    )
    list_filter = ("plan", "status", "cancel_at_period_end")
    search_fields = ("user__username", "user__email", "stripe_customer_id", "stripe_subscription_id")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("user",)
    fieldsets = (
        ("User", {"fields": ("user",)}),
        ("Plan", {"fields": ("plan", "status", "cancel_at_period_end")}),
        ("Stripe", {
            "fields": ("stripe_customer_id", "stripe_subscription_id", "current_period_end"),
        }),
        ("Metadata", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="Paid", boolean=True)
    def is_paid_badge(self, obj: Subscription) -> bool:
        return obj.is_paid


# ---------------------------------------------------------------------------
# CreditBalance — with gift-credits action
# ---------------------------------------------------------------------------

class GiftCreditsForm(forms.Form):
    amount = forms.IntegerField(min_value=1, label="Credits to add")
    description = forms.CharField(
        max_length=200,
        required=False,
        label="Note (visible to user)",
        help_text="Optional. Will appear in their transaction list.",
    )


@admin.register(CreditBalance)
class CreditBalanceAdmin(BaseModelAdmin):
    list_display = ("user", "balance", "ledger_consistency", "updated_at")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("balance", "updated_at", "ledger_consistency")
    autocomplete_fields = ("user",)
    actions = ("add_gift_credits",)

    @admin.display(description="Ledger sum")
    def ledger_consistency(self, obj: CreditBalance) -> str:
        s = ledger_sum(obj.user)
        ok = s == obj.balance
        color = "#16a34a" if ok else "#dc2626"
        label = f"{s} {'OK' if ok else 'DRIFT'}"
        return format_html('<span style="color:{}">{}</span>', color, label)

    @admin.action(description="Add gift credits to selected users")
    def add_gift_credits(self, request, queryset):
        # Two-step action: present a form, then apply.
        from django.shortcuts import render
        from django.urls import reverse
        if "apply" in request.POST:
            form = GiftCreditsForm(request.POST)
            if form.is_valid():
                amount = form.cleaned_data["amount"]
                desc = form.cleaned_data["description"] or "Gift from admin"
                count = 0
                for bal in queryset:
                    add_credits(
                        bal.user, amount,
                        kind="gift",
                        description=desc,
                    )
                    count += 1
                self.message_user(
                    request,
                    f"Added {amount} gift credits to {count} user(s).",
                    level=messages.SUCCESS,
                )
                return None
        else:
            form = GiftCreditsForm()
        return render(
            request,
            "admin/saas_billing_credits_quota/gift_credits.html",
            {
                "form": form,
                "balances": queryset,
                "action_name": "add_gift_credits",
            },
        )


# ---------------------------------------------------------------------------
# CreditTransaction — read-only ledger
# ---------------------------------------------------------------------------

@admin.register(CreditTransaction)
class CreditTransactionAdmin(BaseModelAdmin):
    list_display = (
        "user", "amount", "kind", "resource_key",
        "description", "stripe_session_id", "created_at",
    )
    list_filter = ("kind", "resource_key")
    search_fields = ("user__username", "user__email", "stripe_session_id", "description")
    readonly_fields = (
        "user", "amount", "kind", "resource_key",
        "stripe_session_id", "description", "created_at",
    )
    date_hierarchy = "created_at"

    def has_add_permission(self, request) -> bool:  # type: ignore[override]
        return False

    def has_change_permission(self, request, obj=None) -> bool:  # type: ignore[override]
        # Allow viewing but not editing.
        return False

    def has_delete_permission(self, request, obj=None) -> bool:  # type: ignore[override]
        return False


# ---------------------------------------------------------------------------
# MonthlyQuota
# ---------------------------------------------------------------------------

@admin.register(MonthlyQuota)
class MonthlyQuotaAdmin(BaseModelAdmin):
    list_display = ("user", "resource_key", "month_key", "count", "updated_at")
    list_filter = ("resource_key", "month_key")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("user",)
