"""Exception hierarchy for shop_engine.

Every domain-level failure mode in the engine raises an exception
defined here. Views catch them and translate to a 4xx response with a
stable error code in the JSON body — the frontend matches on the code,
not the message (which is i18n-able and changes).

Why classes instead of a single ``ShopError("CODE", msg)``? Because
``except CouponInvalid`` reads better than ``except ShopError as e: if
e.code == "COUPON_INVALID": ...`` and DRF's ``handler400`` can install
per-class handlers if we ever want to.
"""
from __future__ import annotations


class ShopError(Exception):
    """Base class for every domain error raised by shop_engine."""

    #: Stable error code surfaced to the API consumer (frontend matches on it).
    code: str = "SHOP_ERROR"
    #: HTTP status code the view layer should return.
    http_status: int = 400


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------
class ProductInactive(ShopError):
    code = "PRODUCT_INACTIVE"
    http_status = 400


class VariantInactive(ShopError):
    code = "VARIANT_INACTIVE"
    http_status = 400


class OutOfStock(ShopError):
    code = "OUT_OF_STOCK"
    http_status = 409


# ---------------------------------------------------------------------------
# Cart / checkout
# ---------------------------------------------------------------------------
class CartEmpty(ShopError):
    code = "CART_EMPTY"
    http_status = 400


class CartItemNotFound(ShopError):
    code = "CART_ITEM_NOT_FOUND"
    http_status = 404


class CheckoutGuestEmailRequired(ShopError):
    code = "GUEST_EMAIL_REQUIRED"
    http_status = 400


# ---------------------------------------------------------------------------
# Coupons
# ---------------------------------------------------------------------------
class CouponInvalid(ShopError):
    """Generic catch-all for an unusable coupon (unknown code, disabled, expired)."""

    code = "COUPON_INVALID"
    http_status = 400


class CouponExpired(CouponInvalid):
    code = "COUPON_EXPIRED"


class CouponNotStarted(CouponInvalid):
    code = "COUPON_NOT_STARTED"


class CouponExhausted(CouponInvalid):
    """Either global ``max_uses`` or per-user ``max_uses_per_user`` reached."""

    code = "COUPON_EXHAUSTED"


class CouponMinOrderNotMet(CouponInvalid):
    code = "COUPON_MIN_ORDER"


class CouponProductScopeMismatch(CouponInvalid):
    """Coupon is restricted to specific products and none are in the cart."""

    code = "COUPON_PRODUCT_SCOPE"


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
class OrderNotFound(ShopError):
    code = "ORDER_NOT_FOUND"
    http_status = 404


class InvalidOrderTransition(ShopError):
    """Raised when ``transition_order`` is called with a non-allowed transition."""

    code = "INVALID_ORDER_TRANSITION"
    http_status = 409


class RefundFailed(ShopError):
    code = "REFUND_FAILED"
    http_status = 502


# ---------------------------------------------------------------------------
# Affiliates
# ---------------------------------------------------------------------------
class AffiliateInactive(ShopError):
    code = "AFFILIATE_INACTIVE"
    http_status = 400


class AffiliateLoginInvalid(ShopError):
    """Wrong magic-link token, expired token, or user-affiliate trying magic link."""

    code = "AFFILIATE_LOGIN_INVALID"
    http_status = 401


# ---------------------------------------------------------------------------
# Stripe / payments
# ---------------------------------------------------------------------------
class StripeNotConfigured(ShopError):
    """No STRIPE_SECRET_KEY set. The endpoint returns 503."""

    code = "STRIPE_NOT_CONFIGURED"
    http_status = 503


class WebhookSignatureInvalid(ShopError):
    code = "WEBHOOK_SIGNATURE_INVALID"
    http_status = 400


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------
class ReviewRequiresPurchase(ShopError):
    """``SHOP_REVIEW_REQUIRES_PURCHASE`` is on and the user hasn't bought the product."""

    code = "REVIEW_REQUIRES_PURCHASE"
    http_status = 403


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------
class ProviderError(ShopError):
    """Generic provider failure — sync, dispatch, status fetch."""

    code = "PROVIDER_ERROR"
    http_status = 502


class ProviderNotConfigured(ShopError):
    """The configured provider is missing credentials it needs to operate."""

    code = "PROVIDER_NOT_CONFIGURED"
    http_status = 503
