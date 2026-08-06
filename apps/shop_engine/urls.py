"""URL routing for shop_engine.

Mount once in your project::

    # config/urls.py
    urlpatterns = [
        path("api/shop/", include("shop_engine.urls")),
        # affiliate landing must NOT go under /api/ — it's a redirect:
        path("r/<str:code>/", views.affiliate_landing_view),
    ]

For convenience this module also exposes ``affiliate_landing_urls`` so
projects can mount the landing under a custom prefix.
"""
from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views


router = DefaultRouter()
router.register(r"admin/products", views.AdminProductViewSet, basename="admin-products")
router.register(r"admin/categories", views.AdminCategoryViewSet, basename="admin-categories")
router.register(r"admin/orders", views.AdminOrderViewSet, basename="admin-orders")
router.register(r"admin/coupons", views.AdminCouponViewSet, basename="admin-coupons")
router.register(r"admin/affiliates", views.AdminAffiliateViewSet, basename="admin-affiliates")
router.register(r"admin/affiliate-payouts", views.AdminAffiliatePayoutViewSet, basename="admin-affiliate-payouts")


urlpatterns = [
    # ----- Catalogue (public) -----
    path("products/", views.ProductListView.as_view(), name="shop-products"),
    path("products/<slug:slug>/", views.ProductDetailView.as_view(), name="shop-product-detail"),
    path("products/<slug:slug>/reviews/", views.ProductReviewsListView.as_view(), name="shop-product-reviews"),
    path("categories/", views.CategoryListView.as_view(), name="shop-categories"),

    # ----- Cart -----
    path("cart/", views.CartView.as_view(), name="shop-cart"),
    path("cart/items/", views.CartItemsView.as_view(), name="shop-cart-items"),
    path("cart/items/<int:item_id>/", views.CartItemDetailView.as_view(), name="shop-cart-item-detail"),
    path("cart/apply-coupon/", views.CartApplyCouponView.as_view(), name="shop-cart-apply-coupon"),
    path("cart/remove-coupon/", views.CartRemoveCouponView.as_view(), name="shop-cart-remove-coupon"),

    # ----- Checkout -----
    path("checkout/", views.CheckoutView.as_view(), name="shop-checkout"),

    # ----- Webhooks -----
    path("webhooks/stripe/", views.stripe_webhook_view, name="shop-stripe-webhook"),

    # ----- Orders -----
    path("orders/", views.OrderListView.as_view(), name="shop-orders"),
    path("orders/<str:order_number>/", views.OrderDetailView.as_view(), name="shop-order-detail"),
    path("orders/lookup/", views.GuestOrderLookupView.as_view(), name="shop-order-lookup"),

    # ----- Reviews -----
    path("reviews/", views.ReviewSubmitView.as_view(), name="shop-reviews-submit"),

    # ----- Wishlist -----
    path("wishlist/", views.WishlistView.as_view(), name="shop-wishlist"),
    path("wishlist/items/<int:item_id>/", views.WishlistItemDeleteView.as_view(), name="shop-wishlist-item"),

    # ----- Affiliates (dashboard) -----
    path("affiliates/login/", views.AffiliateLoginView.as_view(), name="shop-affiliate-login"),
    path("affiliates/me/", views.AffiliateMeView.as_view(), name="shop-affiliate-me"),
    path("affiliates/me/conversions/", views.AffiliateMyConversionsView.as_view(), name="shop-affiliate-conversions"),
    path("affiliates/me/payouts/", views.AffiliateMyPayoutsView.as_view(), name="shop-affiliate-payouts"),

    # ----- Admin viewset routes -----
    path("", include(router.urls)),
]


# Convenience extension — mount this in your top-level urls if you want
# the referral landing under your custom prefix. Default mount in the
# top-level urls.py is ``path("r/<str:code>/", views.affiliate_landing_view)``.
affiliate_landing_urls = [
    path("<str:code>/", views.affiliate_landing_view, name="shop-affiliate-landing"),
]
