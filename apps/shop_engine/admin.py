"""Django admin for shop_engine.

Every model is registered with sensible list_display + filters + actions.
Uses django-unfold ``ModelAdmin`` if installed, falls back to vanilla
admin otherwise.

Key actions (the operator daily workflow):

- ProductAdmin       → inline ProductVariant rows
- OrderAdmin         → "Mark fulfilled", "Mark shipped", "Cancel", "Refund (full)"
- AffiliateAdmin     → "Regenerate magic link", "Activate", "Pause"
- AffiliatePayoutAdmin → "Mark paid", "Generate for period" (custom view)
- CouponAdmin        → usage column + "Disable" action
"""
from __future__ import annotations

import csv
import logging

from django.contrib import admin, messages
from django.http import HttpResponse
from django.utils import timezone

try:
    from unfold.admin import ModelAdmin as BaseModelAdmin
    from unfold.admin import TabularInline as BaseTabularInline
except ImportError:  # pragma: no cover - optional dep
    BaseModelAdmin = admin.ModelAdmin  # type: ignore[misc,assignment]
    BaseTabularInline = admin.TabularInline  # type: ignore[misc,assignment]

from .models import (
    Affiliate,
    AffiliateClick,
    AffiliateConversion,
    AffiliatePayout,
    Cart,
    CartItem,
    Category,
    Coupon,
    CouponUsage,
    Order,
    OrderItem,
    Product,
    ProductReview,
    ProductVariant,
    ProviderSyncLog,
    Tag,
    Wishlist,
    WishlistItem,
)
from .services import affiliates as aff_svc
from .services import fulfillment as fulfillment_svc
from .services import orders as orders_svc

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------
@admin.register(Category)
class CategoryAdmin(BaseModelAdmin):
    list_display = ("name", "slug", "parent", "is_active", "order")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Tag)
class TagAdmin(BaseModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name",)


class ProductVariantInline(BaseTabularInline):
    model = ProductVariant
    extra = 0
    fields = ("sku", "label", "price_cents", "stock_quantity", "track_inventory", "is_active")


@admin.register(Product)
class ProductAdmin(BaseModelAdmin):
    list_display = (
        "title", "slug", "provider", "base_price_cents",
        "currency", "is_active", "is_featured", "updated_at",
    )
    list_filter = ("is_active", "is_featured", "provider", "currency", "category")
    search_fields = ("title", "slug", "external_id")
    prepopulated_fields = {"slug": ("title",)}
    autocomplete_fields = ("category", "tags")
    inlines = (ProductVariantInline,)
    readonly_fields = ("created_at", "updated_at")


@admin.register(ProductVariant)
class ProductVariantAdmin(BaseModelAdmin):
    list_display = ("sku", "product", "label", "price_cents", "stock_quantity", "is_active")
    list_filter = ("is_active", "track_inventory")
    search_fields = ("sku", "label", "product__title")
    autocomplete_fields = ("product",)


@admin.register(ProductReview)
class ProductReviewAdmin(BaseModelAdmin):
    list_display = (
        "product", "rating", "is_verified_purchase",
        "is_published", "author_name_snapshot", "created_at",
    )
    list_filter = ("is_verified_purchase", "is_published", "rating")
    search_fields = ("product__title", "title", "body", "author_name_snapshot")
    autocomplete_fields = ("product", "user")
    readonly_fields = ("is_verified_purchase", "created_at", "updated_at")


# ---------------------------------------------------------------------------
# Wishlist
# ---------------------------------------------------------------------------
@admin.register(Wishlist)
class WishlistAdmin(BaseModelAdmin):
    list_display = ("user", "created_at", "updated_at")
    search_fields = ("user__username", "user__email")
    autocomplete_fields = ("user",)


@admin.register(WishlistItem)
class WishlistItemAdmin(BaseModelAdmin):
    list_display = ("wishlist", "product", "variant", "added_at")
    autocomplete_fields = ("wishlist", "product", "variant")


# ---------------------------------------------------------------------------
# Cart
# ---------------------------------------------------------------------------
class CartItemInline(BaseTabularInline):
    model = CartItem
    extra = 0
    fields = ("product", "variant", "quantity", "unit_price_cents")
    autocomplete_fields = ("product", "variant")


@admin.register(Cart)
class CartAdmin(BaseModelAdmin):
    list_display = ("id", "user", "session_key", "applied_coupon", "updated_at")
    list_filter = ("currency",)
    search_fields = ("user__username", "user__email", "session_key")
    autocomplete_fields = ("user", "applied_coupon")
    inlines = (CartItemInline,)


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
class OrderItemInline(BaseTabularInline):
    model = OrderItem
    extra = 0
    fields = ("product_title", "variant_label", "sku", "quantity", "unit_price_cents", "line_total_cents")
    readonly_fields = fields
    can_delete = False


@admin.register(Order)
class OrderAdmin(BaseModelAdmin):
    list_display = (
        "order_number", "status", "email", "total_cents", "currency",
        "affiliate_code", "applied_coupon_code", "created_at",
    )
    list_filter = ("status", "currency", "created_at")
    search_fields = ("order_number", "email", "stripe_payment_intent_id", "user__username")
    autocomplete_fields = ("user",)
    readonly_fields = (
        "order_number", "stripe_payment_intent_id", "stripe_charge_id",
        "applied_coupon_code", "affiliate_code", "provider_metadata",
        "subtotal_cents", "shipping_cents", "tax_cents",
        "discount_cents", "total_cents", "currency",
        "placed_at", "paid_at", "fulfilled_at", "shipped_at",
        "delivered_at", "cancelled_at", "refunded_at",
        "created_at", "updated_at",
    )
    inlines = (OrderItemInline,)
    actions = ("action_refund_full", "action_mark_fulfilled", "action_mark_shipped", "action_cancel", "action_export_csv")

    @admin.action(description="Refund (full)")
    def action_refund_full(self, request, queryset):
        n, errors = 0, 0
        for order in queryset:
            try:
                orders_svc.refund_order(order)
                n += 1
            except Exception as exc:
                errors += 1
                self.message_user(request, f"{order.order_number}: {exc}", messages.ERROR)
        if n:
            self.message_user(request, f"Refunded {n} order(s).", messages.SUCCESS)

    @admin.action(description="Mark fulfilling (dispatch to provider)")
    def action_mark_fulfilled(self, request, queryset):
        n = 0
        for order in queryset:
            try:
                fulfillment_svc.dispatch_to_provider(order)
                n += 1
            except Exception as exc:
                self.message_user(request, f"{order.order_number}: {exc}", messages.ERROR)
        self.message_user(request, f"Dispatched {n} order(s).", messages.SUCCESS)

    @admin.action(description="Mark shipped (manual)")
    def action_mark_shipped(self, request, queryset):
        n = 0
        for order in queryset:
            try:
                fulfillment_svc.mark_shipped(order)
                n += 1
            except Exception as exc:
                self.message_user(request, f"{order.order_number}: {exc}", messages.ERROR)
        self.message_user(request, f"Marked {n} order(s) shipped.", messages.SUCCESS)

    @admin.action(description="Cancel")
    def action_cancel(self, request, queryset):
        n = 0
        for order in queryset:
            try:
                orders_svc.transition_order(order, new_status=Order.STATUS_CANCELLED)
                n += 1
            except Exception as exc:
                self.message_user(request, f"{order.order_number}: {exc}", messages.ERROR)
        self.message_user(request, f"Cancelled {n} order(s).", messages.SUCCESS)

    @admin.action(description="Export selected to CSV")
    def action_export_csv(self, request, queryset):
        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = f'attachment; filename="orders_{timezone.now():%Y%m%d}.csv"'
        writer = csv.writer(resp)
        writer.writerow([
            "order_number", "status", "email", "total_cents", "currency",
            "affiliate_code", "applied_coupon_code", "created_at",
        ])
        for o in queryset:
            writer.writerow([
                o.order_number, o.status, o.email, o.total_cents, o.currency,
                o.affiliate_code, o.applied_coupon_code, o.created_at,
            ])
        return resp


@admin.register(OrderItem)
class OrderItemAdmin(BaseModelAdmin):
    list_display = ("order", "product_title", "variant_label", "quantity", "line_total_cents")
    search_fields = ("order__order_number", "product_title", "sku")


# ---------------------------------------------------------------------------
# Coupons
# ---------------------------------------------------------------------------
@admin.register(Coupon)
class CouponAdmin(BaseModelAdmin):
    list_display = (
        "code", "kind", "value", "is_active",
        "times_used", "max_uses", "starts_at", "expires_at",
    )
    list_filter = ("kind", "is_active")
    search_fields = ("code",)
    filter_horizontal = ("product_scope",)
    readonly_fields = ("times_used", "created_at", "updated_at")
    actions = ("action_disable",)

    @admin.action(description="Disable (set is_active=False)")
    def action_disable(self, request, queryset):
        n = queryset.update(is_active=False)
        self.message_user(request, f"Disabled {n} coupon(s).", messages.SUCCESS)


@admin.register(CouponUsage)
class CouponUsageAdmin(BaseModelAdmin):
    list_display = ("coupon", "order", "user", "used_at")
    search_fields = ("coupon__code", "order__order_number")
    readonly_fields = tuple(f.name for f in CouponUsage._meta.fields)


# ---------------------------------------------------------------------------
# Affiliates
# ---------------------------------------------------------------------------
@admin.register(Affiliate)
class AffiliateAdmin(BaseModelAdmin):
    list_display = (
        "code", "email_or_user", "status", "commission_bps",
        "flat_per_order_cents", "total_clicks", "total_conversions", "total_paid_cents",
    )
    list_filter = ("status", "payout_method")
    search_fields = ("code", "email", "display_name", "user__username")
    autocomplete_fields = ("user",)
    readonly_fields = (
        "code", "magic_link_token", "magic_link_sent_at",
        "total_clicks", "total_conversions", "total_paid_cents",
        "created_at", "updated_at",
    )
    actions = (
        "action_regenerate_magic_link",
        "action_activate",
        "action_pause",
    )

    @admin.display(description="Affiliate")
    def email_or_user(self, obj: Affiliate) -> str:
        if obj.user_id:
            return f"{obj.user} ({obj.email})"
        return obj.email

    @admin.action(description="Regenerate magic link")
    def action_regenerate_magic_link(self, request, queryset):
        n = 0
        for affiliate in queryset:
            token = aff_svc.regenerate_magic_link(affiliate)
            if token:
                n += 1
        self.message_user(request, f"Regenerated magic link for {n} affiliate(s).", messages.SUCCESS)

    @admin.action(description="Activate (status=active)")
    def action_activate(self, request, queryset):
        n = queryset.update(status=Affiliate.STATUS_ACTIVE)
        self.message_user(request, f"Activated {n}.", messages.SUCCESS)

    @admin.action(description="Pause (status=paused)")
    def action_pause(self, request, queryset):
        n = queryset.update(status=Affiliate.STATUS_PAUSED)
        self.message_user(request, f"Paused {n}.", messages.SUCCESS)


@admin.register(AffiliateClick)
class AffiliateClickAdmin(BaseModelAdmin):
    list_display = ("affiliate", "ip", "referer", "created_at")
    list_filter = ("affiliate",)
    search_fields = ("affiliate__code", "ip", "referer")
    readonly_fields = tuple(f.name for f in AffiliateClick._meta.fields)
    date_hierarchy = "created_at"

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False


@admin.register(AffiliateConversion)
class AffiliateConversionAdmin(BaseModelAdmin):
    list_display = (
        "affiliate", "order", "commission_cents", "status",
        "paid_at", "created_at",
    )
    list_filter = ("status",)
    search_fields = ("affiliate__code", "order__order_number")
    readonly_fields = tuple(f.name for f in AffiliateConversion._meta.fields)
    date_hierarchy = "created_at"


@admin.register(AffiliatePayout)
class AffiliatePayoutAdmin(BaseModelAdmin):
    list_display = (
        "affiliate", "period_start", "period_end",
        "conversion_count", "commission_cents", "fee_cents",
        "net_cents", "status", "paid_at",
    )
    list_filter = ("status",)
    search_fields = ("affiliate__code", "external_payout_id")
    readonly_fields = (
        "conversion_count", "gross_cents", "commission_cents", "net_cents",
        "paid_at", "paid_by", "created_at",
    )
    actions = ("action_mark_paid",)

    @admin.action(description="Mark paid (no external_payout_id — use the API for that)")
    def action_mark_paid(self, request, queryset):
        n = 0
        for payout in queryset:
            try:
                aff_svc.mark_payout_paid(
                    payout, paid_by=request.user if request.user.is_authenticated else None,
                )
                n += 1
            except Exception as exc:
                self.message_user(request, f"#{payout.pk}: {exc}", messages.ERROR)
        self.message_user(request, f"Marked {n} payout(s) paid.", messages.SUCCESS)


# ---------------------------------------------------------------------------
# Provider sync log (read-only audit)
# ---------------------------------------------------------------------------
@admin.register(ProviderSyncLog)
class ProviderSyncLogAdmin(BaseModelAdmin):
    list_display = ("provider", "action", "external_id", "status", "created_at")
    list_filter = ("provider", "action", "status")
    search_fields = ("external_id", "error_message")
    readonly_fields = tuple(f.name for f in ProviderSyncLog._meta.fields)
    date_hierarchy = "created_at"

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False
