"""DRF serializers for the public + admin APIs.

These are intentionally small — most validation lives in the services
layer (so the same rules apply to admin actions, signals, and
management commands, not just the API). The serializers are mostly
"shape + read-only fields".
"""
from __future__ import annotations

from rest_framework import serializers

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
    Tag,
    Wishlist,
    WishlistItem,
)


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------
class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ("id", "name")


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ("id", "name", "slug", "parent", "description", "is_active", "order")


class ProductVariantSerializer(serializers.ModelSerializer):
    # ``effective_price_cents`` is a method on the model, not a field —
    # use SerializerMethodField rather than ``source=`` so DRF actually
    # calls it (a plain IntegerField(source=) would refuse a callable).
    effective_price_cents = serializers.SerializerMethodField()

    class Meta:
        model = ProductVariant
        fields = (
            "id", "sku", "label", "price_cents", "effective_price_cents",
            "stock_quantity", "track_inventory", "attributes", "weight_grams",
            "is_active",
        )

    def get_effective_price_cents(self, obj: ProductVariant) -> int:
        return obj.effective_price_cents()


class ProductSerializer(serializers.ModelSerializer):
    variants = ProductVariantSerializer(many=True, read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    category = CategorySerializer(read_only=True)
    primary_image_url = serializers.CharField(read_only=True)

    class Meta:
        model = Product
        fields = (
            "id", "title", "slug", "description", "category", "tags",
            "is_active", "is_featured", "provider", "external_id",
            "base_price_cents", "currency", "images", "primary_image_url",
            "seo_title", "seo_description", "variants",
            "created_at", "updated_at",
        )
        read_only_fields = ("provider", "external_id", "created_at", "updated_at")


class ProductReviewSerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()

    class Meta:
        model = ProductReview
        fields = (
            "id", "product", "rating", "title", "body",
            "is_verified_purchase", "is_published", "author",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "is_verified_purchase", "is_published",
            "author", "created_at", "updated_at",
        )

    def get_author(self, obj: ProductReview) -> str:
        return obj.author_name_snapshot or (str(obj.user) if obj.user else "Anonymous")


# ---------------------------------------------------------------------------
# Cart
# ---------------------------------------------------------------------------
class CartItemSerializer(serializers.ModelSerializer):
    line_total_cents = serializers.IntegerField(read_only=True)
    product = ProductSerializer(read_only=True)
    variant = ProductVariantSerializer(read_only=True)

    class Meta:
        model = CartItem
        fields = (
            "id", "product", "variant", "quantity",
            "unit_price_cents", "line_total_cents",
            "created_at", "updated_at",
        )
        read_only_fields = ("unit_price_cents", "line_total_cents", "created_at", "updated_at")


class CartSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(many=True, read_only=True)
    totals = serializers.SerializerMethodField()

    class Meta:
        model = Cart
        fields = (
            "id", "currency", "applied_coupon", "affiliate_code",
            "items", "totals", "created_at", "updated_at",
        )
        read_only_fields = fields

    def get_totals(self, obj: Cart) -> dict:
        from .services.cart import calculate_totals
        return calculate_totals(obj)


class AddToCartSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    variant_id = serializers.IntegerField(required=False, allow_null=True)
    quantity = serializers.IntegerField(min_value=1, default=1)


class UpdateCartItemSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=0)


class ApplyCouponSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=80)


# ---------------------------------------------------------------------------
# Checkout / orders
# ---------------------------------------------------------------------------
class AddressSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    line1 = serializers.CharField(max_length=200)
    line2 = serializers.CharField(max_length=200, required=False, allow_blank=True)
    city = serializers.CharField(max_length=120)
    region = serializers.CharField(max_length=120, required=False, allow_blank=True)
    postal_code = serializers.CharField(max_length=20)
    country = serializers.CharField(max_length=2, default="CA")
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True)


class CheckoutSerializer(serializers.Serializer):
    billing_address = AddressSerializer()
    shipping_address = AddressSerializer(required=False)
    customer_email = serializers.EmailField(required=False, allow_blank=True)
    customer_notes = serializers.CharField(max_length=2000, required=False, allow_blank=True)


class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = (
            "id", "product", "variant",
            "product_title", "variant_label", "sku",
            "unit_price_cents", "quantity", "line_total_cents",
        )
        read_only_fields = fields


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = (
            "id", "order_number", "user", "status", "email",
            "billing_address", "shipping_address",
            "subtotal_cents", "shipping_cents", "tax_cents",
            "discount_cents", "total_cents", "currency",
            "stripe_payment_intent_id", "stripe_charge_id",
            "applied_coupon_code", "affiliate_code",
            "provider_metadata", "customer_notes",
            "placed_at", "paid_at", "fulfilled_at", "shipped_at",
            "delivered_at", "cancelled_at", "refunded_at",
            "items", "created_at", "updated_at",
        )
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Coupons
# ---------------------------------------------------------------------------
class CouponSerializer(serializers.ModelSerializer):
    class Meta:
        model = Coupon
        fields = (
            "id", "code", "kind", "value", "max_uses", "max_uses_per_user",
            "times_used", "starts_at", "expires_at", "minimum_order_cents",
            "product_scope", "is_active", "created_at", "updated_at",
        )
        read_only_fields = ("times_used", "created_at", "updated_at")


# ---------------------------------------------------------------------------
# Affiliates
# ---------------------------------------------------------------------------
class AffiliateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Affiliate
        fields = (
            "id", "user", "email", "payout_email", "code", "display_name",
            "commission_bps", "flat_per_order_cents",
            "status", "payout_method", "payout_details",
            "total_clicks", "total_conversions", "total_paid_cents",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "code", "total_clicks", "total_conversions", "total_paid_cents",
            "created_at", "updated_at",
        )


class AffiliateConversionSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True)

    class Meta:
        model = AffiliateConversion
        fields = (
            "id", "order", "order_number", "click",
            "gross_cents", "commission_bps_applied", "flat_per_order_cents_applied",
            "commission_cents", "status", "paid_at", "payout", "created_at",
        )
        read_only_fields = fields


class AffiliatePayoutSerializer(serializers.ModelSerializer):
    class Meta:
        model = AffiliatePayout
        fields = (
            "id", "affiliate", "period_start", "period_end",
            "conversion_count", "gross_cents", "commission_cents",
            "fee_cents", "net_cents", "status", "external_payout_id",
            "notes", "paid_at", "paid_by", "created_at",
        )
        read_only_fields = (
            "conversion_count", "gross_cents", "commission_cents", "net_cents",
            "paid_at", "paid_by", "created_at",
        )


class AffiliateLoginSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False)
    token = serializers.CharField(required=False)


# ---------------------------------------------------------------------------
# Wishlist
# ---------------------------------------------------------------------------
class WishlistItemSerializer(serializers.ModelSerializer):
    product = ProductSerializer(read_only=True)
    variant = ProductVariantSerializer(read_only=True)

    class Meta:
        model = WishlistItem
        fields = ("id", "product", "variant", "notes", "added_at")
        read_only_fields = ("added_at",)


class WishlistSerializer(serializers.ModelSerializer):
    items = WishlistItemSerializer(many=True, read_only=True)

    class Meta:
        model = Wishlist
        fields = ("id", "items", "created_at", "updated_at")
        read_only_fields = fields
