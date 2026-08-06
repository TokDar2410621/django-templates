"""HTTP views — public catalogue + cart + checkout + admin + affiliate dashboard.

Each view is thin — it parses input, delegates to a service or selector,
returns the right shape. Exceptions raised by services are caught by
``_exception_to_response`` and converted to ``{detail, code}`` JSON.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .exceptions import ShopError
from .models import (
    Affiliate,
    AffiliatePayout,
    Cart,
    Category,
    Coupon,
    Order,
    Product,
    ProductReview,
    ProductVariant,
    Wishlist,
    WishlistItem,
)
from .selectors import (
    active_products,
    affiliate_dashboard_data,
    category_tree,
    order_for_email,
    order_for_user,
    order_history,
    reviews_for_product,
)
from .serializers import (
    AddToCartSerializer,
    AffiliateConversionSerializer,
    AffiliateLoginSerializer,
    AffiliatePayoutSerializer,
    AffiliateSerializer,
    ApplyCouponSerializer,
    CartSerializer,
    CategorySerializer,
    CheckoutSerializer,
    CouponSerializer,
    OrderSerializer,
    ProductReviewSerializer,
    ProductSerializer,
    UpdateCartItemSerializer,
    WishlistItemSerializer,
    WishlistSerializer,
)
from .services import (
    affiliates as aff_svc,
    cart as cart_svc,
    checkout as checkout_svc,
    fulfillment as fulfillment_svc,
    orders as orders_svc,
    reviews as reviews_svc,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exception → response
# ---------------------------------------------------------------------------
def _exception_to_response(exc: Exception) -> Response:
    """Map a ``ShopError`` to a JSON ``{detail, code}`` response."""
    if isinstance(exc, ShopError):
        return Response(
            {"detail": str(exc), "code": exc.code},
            status=exc.http_status,
        )
    logger.exception("Unhandled exception in shop_engine view")
    return Response(
        {"detail": "Internal server error.", "code": "INTERNAL_ERROR"},
        status=500,
    )


# ---------------------------------------------------------------------------
# Catalogue (public)
# ---------------------------------------------------------------------------
class ProductListView(APIView):
    """``GET /api/shop/products/`` — paginated product list with filters."""

    permission_classes = [AllowAny]

    def get(self, request) -> Response:
        qs = active_products()
        q = request.GET.get("q")
        if q:
            qs = qs.filter(title__icontains=q)
        if request.GET.get("category"):
            qs = qs.filter(category__slug=request.GET["category"])
        if request.GET.get("tag"):
            qs = qs.filter(tags__name=request.GET["tag"])
        if request.GET.get("featured") == "1":
            qs = qs.filter(is_featured=True)

        try:
            page = max(int(request.GET.get("page", 1)), 1)
            page_size = min(max(int(request.GET.get("page_size", 24)), 1), 100)
        except ValueError:
            page, page_size = 1, 24

        total = qs.count()
        offset = (page - 1) * page_size
        rows = qs.distinct()[offset:offset + page_size]

        return Response({
            "results": ProductSerializer(rows, many=True).data,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_next": offset + page_size < total,
        })


class ProductDetailView(APIView):
    """``GET /api/shop/products/<slug>/`` — full product payload."""

    permission_classes = [AllowAny]

    def get(self, request, slug: str) -> Response:
        product = get_object_or_404(active_products(), slug=slug)
        return Response(ProductSerializer(product).data)


class CategoryListView(APIView):
    """``GET /api/shop/categories/`` — nested category tree."""

    permission_classes = [AllowAny]

    def get(self, request) -> Response:
        return Response(category_tree())


class ProductReviewsListView(APIView):
    """``GET /api/shop/products/<slug>/reviews/`` — published reviews."""

    permission_classes = [AllowAny]

    def get(self, request, slug: str) -> Response:
        product = get_object_or_404(active_products(), slug=slug)
        reviews = reviews_for_product(product)
        return Response(ProductReviewSerializer(reviews, many=True).data)


# ---------------------------------------------------------------------------
# Cart
# ---------------------------------------------------------------------------
class CartView(APIView):
    """``GET /api/shop/cart/`` — current cart (auto-created if missing)."""

    permission_classes = [AllowAny]

    def get(self, request) -> Response:
        cart = cart_svc.get_or_create_cart_for_request(request)
        return Response(CartSerializer(cart).data)


class CartItemsView(APIView):
    """``POST /api/shop/cart/items/`` — add to cart."""

    permission_classes = [AllowAny]

    def post(self, request) -> Response:
        s = AddToCartSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            cart = cart_svc.get_or_create_cart_for_request(request)
            product = get_object_or_404(Product, pk=s.validated_data["product_id"])
            variant = None
            if s.validated_data.get("variant_id"):
                variant = get_object_or_404(ProductVariant, pk=s.validated_data["variant_id"])
            cart_svc.add_to_cart(
                cart, product=product, variant=variant,
                quantity=s.validated_data["quantity"],
            )
        except Exception as exc:
            return _exception_to_response(exc)
        return Response(CartSerializer(cart).data, status=201)


class CartItemDetailView(APIView):
    """``PATCH /api/shop/cart/items/<id>/`` — update qty / ``DELETE`` — remove."""

    permission_classes = [AllowAny]

    def patch(self, request, item_id: int) -> Response:
        s = UpdateCartItemSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            cart = cart_svc.get_or_create_cart_for_request(request)
            item = cart_svc.get_cart_item(cart, item_id)
            cart_svc.update_quantity(item, quantity=s.validated_data["quantity"])
        except Exception as exc:
            return _exception_to_response(exc)
        return Response(CartSerializer(cart).data)

    def delete(self, request, item_id: int) -> Response:
        try:
            cart = cart_svc.get_or_create_cart_for_request(request)
            item = cart_svc.get_cart_item(cart, item_id)
            cart_svc.remove_from_cart(item)
        except Exception as exc:
            return _exception_to_response(exc)
        return Response(CartSerializer(cart).data)


class CartApplyCouponView(APIView):
    permission_classes = [AllowAny]

    def post(self, request) -> Response:
        s = ApplyCouponSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            cart = cart_svc.get_or_create_cart_for_request(request)
            cart_svc.apply_coupon(cart, code=s.validated_data["code"])
        except Exception as exc:
            return _exception_to_response(exc)
        return Response(CartSerializer(cart).data)


class CartRemoveCouponView(APIView):
    permission_classes = [AllowAny]

    def post(self, request) -> Response:
        cart = cart_svc.get_or_create_cart_for_request(request)
        cart_svc.revoke_coupon(cart)
        return Response(CartSerializer(cart).data)


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------
class CheckoutView(APIView):
    """``POST /api/shop/checkout/`` — turn cart into Order + return PI client_secret."""

    permission_classes = [AllowAny]

    def post(self, request) -> Response:
        s = CheckoutSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            cart = cart_svc.get_or_create_cart_for_request(request)
            order, client_secret = checkout_svc.create_checkout(
                cart,
                billing_address=s.validated_data["billing_address"],
                shipping_address=s.validated_data.get("shipping_address") or s.validated_data["billing_address"],
                customer_email=s.validated_data.get("customer_email") or "",
                customer_notes=s.validated_data.get("customer_notes") or "",
            )
        except Exception as exc:
            return _exception_to_response(exc)
        return Response({
            "order_number": order.order_number,
            "stripe_client_secret": client_secret,
            "order": OrderSerializer(order).data,
        })


# ---------------------------------------------------------------------------
# Stripe webhook
# ---------------------------------------------------------------------------
@api_view(["POST"])
@permission_classes([AllowAny])
def stripe_webhook_view(request) -> Response:
    """``POST /api/shop/webhooks/stripe/`` — Stripe-signed payment events."""
    sig = request.META.get("HTTP_STRIPE_SIGNATURE", "")
    try:
        checkout_svc.process_stripe_webhook(payload=request.body, signature_header=sig)
    except ShopError as exc:
        return _exception_to_response(exc)
    except Exception as exc:
        # Don't 500 — Stripe will retry forever on 5xx. Log + 400.
        logger.exception("Stripe webhook processing failed")
        return Response({"detail": str(exc), "code": "WEBHOOK_ERROR"}, status=400)
    return Response({"received": True})


# ---------------------------------------------------------------------------
# Orders (auth, owner-only)
# ---------------------------------------------------------------------------
class OrderListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request) -> Response:
        orders = order_history(request.user)
        return Response(OrderSerializer(orders, many=True).data)


class OrderDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, order_number: str) -> Response:
        order = order_for_user(user=request.user, order_number=order_number)
        if order is None:
            return Response({"detail": "Order not found.", "code": "ORDER_NOT_FOUND"}, status=404)
        return Response(OrderSerializer(order).data)


class GuestOrderLookupView(APIView):
    """``POST /api/shop/orders/lookup/`` — guest-friendly lookup by ``(email, order_number)``."""

    permission_classes = [AllowAny]

    def post(self, request) -> Response:
        email = (request.data.get("email") or "").strip()
        order_number = (request.data.get("order_number") or "").strip()
        if not (email and order_number):
            return Response({"detail": "email + order_number required."}, status=400)
        order = order_for_email(email=email, order_number=order_number)
        if order is None:
            return Response({"detail": "Order not found.", "code": "ORDER_NOT_FOUND"}, status=404)
        return Response(OrderSerializer(order).data)


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------
class ReviewSubmitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request) -> Response:
        s = ProductReviewSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            product = get_object_or_404(Product, pk=s.validated_data["product"].pk)
            review = reviews_svc.submit_review(
                user=request.user,
                product=product,
                rating=s.validated_data["rating"],
                title=s.validated_data.get("title") or "",
                body=s.validated_data.get("body") or "",
            )
        except Exception as exc:
            return _exception_to_response(exc)
        return Response(ProductReviewSerializer(review).data, status=201)


# ---------------------------------------------------------------------------
# Wishlist
# ---------------------------------------------------------------------------
class WishlistView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request) -> Response:
        wishlist, _ = Wishlist.objects.get_or_create(user=request.user)
        return Response(WishlistSerializer(wishlist).data)

    def post(self, request) -> Response:
        wishlist, _ = Wishlist.objects.get_or_create(user=request.user)
        product = get_object_or_404(Product, pk=request.data.get("product_id"))
        variant = None
        if request.data.get("variant_id"):
            variant = get_object_or_404(ProductVariant, pk=request.data["variant_id"])
        item, _ = WishlistItem.objects.get_or_create(
            wishlist=wishlist, product=product, variant=variant,
            defaults={"notes": request.data.get("notes") or ""},
        )
        return Response(WishlistItemSerializer(item).data, status=201)


class WishlistItemDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, item_id: int) -> Response:
        wishlist = get_object_or_404(Wishlist, user=request.user)
        item = get_object_or_404(WishlistItem, pk=item_id, wishlist=wishlist)
        item.delete()
        return Response(status=204)


# ---------------------------------------------------------------------------
# Affiliate landing (public) — ``/r/<code>/``
# ---------------------------------------------------------------------------
def affiliate_landing_view(request, code: str):
    """``GET /r/<code>/`` — record click + redirect to landing URL.

    Plain Django view (not DRF) because we 302-redirect with cookies,
    which doesn't fit DRF's Response shape cleanly.
    """
    landing_url = getattr(settings, "SHOP_AFFILIATE_LANDING_URL", "/")
    cookie_name = getattr(settings, "SHOP_AFFILIATE_COOKIE_NAME", "_shop_ref")
    cookie_ttl_days = int(getattr(settings, "SHOP_AFFILIATE_COOKIE_TTL_DAYS", 30))

    click = aff_svc.track_click(code=code, request=request)
    response = HttpResponseRedirect(landing_url)
    response.set_cookie(
        cookie_name,
        value=code,
        max_age=cookie_ttl_days * 24 * 3600,
        secure=not getattr(settings, "DEBUG", False),
        httponly=False,  # accessible to FE JS so it can copy onto Cart.affiliate_code
        samesite="Lax",
    )
    if click is not None:
        response.set_cookie(
            f"{cookie_name}_cookie_id",
            value=str(click.cookie_id),
            max_age=cookie_ttl_days * 24 * 3600,
            secure=not getattr(settings, "DEBUG", False),
            httponly=False,
            samesite="Lax",
        )
    return response


# ---------------------------------------------------------------------------
# Affiliate dashboard
# ---------------------------------------------------------------------------
def _resolve_affiliate_from_request(request) -> Affiliate:
    """Resolve current affiliate — magic-link token OR authenticated user.

    Raises ``ShopError`` on failure (caught upstream).
    """
    # Token can come on the query string (GET) or the POST body.
    token = request.GET.get("token", "")
    if not token and hasattr(request, "data"):
        token = request.data.get("token", "") or ""
    if token:
        return aff_svc.resolve_affiliate_from_token(token)
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        affiliate = Affiliate.objects.filter(user=user).first()
        if affiliate is None:
            from .exceptions import AffiliateLoginInvalid
            raise AffiliateLoginInvalid("No affiliate row for this user.")
        return affiliate
    from .exceptions import AffiliateLoginInvalid
    raise AffiliateLoginInvalid("Provide ?token=... or authenticate.")


class AffiliateLoginView(APIView):
    """``POST /api/shop/affiliates/login/`` — request a magic link.

    Body: ``{email}`` — for an email-only affiliate, looks up the row by
    email, rotates its magic-link token, and (the project's email layer)
    sends them the URL.

    The view does **NOT send the email itself** — it returns the token
    and the project is responsible for routing it through
    ``notifications-multichannel`` / Resend / whatever. This keeps the
    template independent of an email backend.
    """

    permission_classes = [AllowAny]

    def post(self, request) -> Response:
        s = AffiliateLoginSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        email = s.validated_data.get("email")
        if not email:
            return Response({"detail": "email is required.", "code": "EMAIL_REQUIRED"}, status=400)
        affiliate = Affiliate.objects.filter(email__iexact=email, user__isnull=True).first()
        if affiliate is None:
            # Privacy-friendly: return the same 200 regardless to avoid email enumeration.
            logger.info("Affiliate login attempt for non-existent email %s", email)
            return Response({"detail": "If an account exists, a magic link is on its way.", "ok": True})
        token = aff_svc.regenerate_magic_link(affiliate)
        # Project hook — the API consumer is expected to wire this up.
        # ``DEBUG=True`` projects can read the response body in dev.
        payload = {"detail": "If an account exists, a magic link is on its way.", "ok": True}
        if getattr(settings, "DEBUG", False):
            payload["dev_token"] = token
            payload["dev_code"] = affiliate.code
        return Response(payload)


class AffiliateMeView(APIView):
    permission_classes = [AllowAny]

    def get(self, request) -> Response:
        try:
            affiliate = _resolve_affiliate_from_request(request)
        except Exception as exc:
            return _exception_to_response(exc)
        return Response(affiliate_dashboard_data(affiliate))


class AffiliateMyConversionsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request) -> Response:
        try:
            affiliate = _resolve_affiliate_from_request(request)
        except Exception as exc:
            return _exception_to_response(exc)
        convs = affiliate.conversions.select_related("order").order_by("-created_at")[:200]
        return Response(AffiliateConversionSerializer(convs, many=True).data)


class AffiliateMyPayoutsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request) -> Response:
        try:
            affiliate = _resolve_affiliate_from_request(request)
        except Exception as exc:
            return _exception_to_response(exc)
        payouts = affiliate.payouts.order_by("-created_at")
        return Response(AffiliatePayoutSerializer(payouts, many=True).data)


# ---------------------------------------------------------------------------
# Admin API (staff only)
# ---------------------------------------------------------------------------
class AdminProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all().prefetch_related("variants", "tags").select_related("category")
    serializer_class = ProductSerializer
    permission_classes = [IsAdminUser]
    lookup_field = "slug"


class AdminCategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [IsAdminUser]


class AdminOrderViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Order.objects.all().prefetch_related("items")
    serializer_class = OrderSerializer
    permission_classes = [IsAdminUser]
    lookup_field = "order_number"

    @action(detail=True, methods=["post"])
    def refund(self, request, order_number=None) -> Response:
        order = self.get_object()
        amount = request.data.get("amount_cents")
        reason = request.data.get("reason", "")
        try:
            orders_svc.refund_order(
                order,
                amount_cents=int(amount) if amount is not None else None,
                reason=reason,
            )
        except Exception as exc:
            return _exception_to_response(exc)
        return Response(OrderSerializer(order).data)

    @action(detail=True, methods=["post"])
    def mark_fulfilled(self, request, order_number=None) -> Response:
        order = self.get_object()
        try:
            fulfillment_svc.dispatch_to_provider(order)
        except Exception as exc:
            return _exception_to_response(exc)
        return Response(OrderSerializer(order).data)

    @action(detail=True, methods=["post"])
    def mark_shipped(self, request, order_number=None) -> Response:
        order = self.get_object()
        try:
            fulfillment_svc.mark_shipped(
                order,
                tracking_number=request.data.get("tracking_number") or "",
                tracking_url=request.data.get("tracking_url") or "",
                carrier=request.data.get("carrier") or "",
            )
        except Exception as exc:
            return _exception_to_response(exc)
        return Response(OrderSerializer(order).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, order_number=None) -> Response:
        order = self.get_object()
        try:
            orders_svc.transition_order(order, new_status=Order.STATUS_CANCELLED)
        except Exception as exc:
            return _exception_to_response(exc)
        return Response(OrderSerializer(order).data)


class AdminCouponViewSet(viewsets.ModelViewSet):
    queryset = Coupon.objects.all()
    serializer_class = CouponSerializer
    permission_classes = [IsAdminUser]


class AdminAffiliateViewSet(viewsets.ModelViewSet):
    queryset = Affiliate.objects.all()
    serializer_class = AffiliateSerializer
    permission_classes = [IsAdminUser]

    @action(detail=True, methods=["post"])
    def regenerate_magic_link(self, request, pk=None) -> Response:
        affiliate = self.get_object()
        token = aff_svc.regenerate_magic_link(affiliate)
        return Response({"token": token, "code": affiliate.code})


class AdminAffiliatePayoutViewSet(viewsets.ModelViewSet):
    """Admin endpoint over ``AffiliatePayout`` rows."""

    queryset = AffiliatePayout.objects.all().select_related("affiliate")
    serializer_class = AffiliatePayoutSerializer
    permission_classes = [IsAdminUser]

    @action(detail=True, methods=["post"])
    def mark_paid(self, request, pk=None) -> Response:
        payout = get_object_or_404(AffiliatePayout, pk=pk)
        try:
            aff_svc.mark_payout_paid(
                payout,
                external_payout_id=request.data.get("external_payout_id") or "",
                fee_cents=int(request.data.get("fee_cents") or 0),
                paid_by=request.user if request.user.is_authenticated else None,
                notes=request.data.get("notes") or "",
            )
        except Exception as exc:
            return _exception_to_response(exc)
        return Response(AffiliatePayoutSerializer(payout).data)

    @action(detail=False, methods=["post"])
    def generate_for_period(self, request) -> Response:
        """Body: ``{period_start, period_end}`` (ISO dates) — generate for every active affiliate."""
        period_start = request.data.get("period_start")
        period_end = request.data.get("period_end")
        if not (period_start and period_end):
            return Response({"detail": "period_start + period_end required."}, status=400)
        from datetime import datetime
        try:
            ps = datetime.fromisoformat(period_start)
            pe = datetime.fromisoformat(period_end)
        except Exception:
            return Response({"detail": "ISO format required."}, status=400)
        created: list[dict] = []
        for affiliate in Affiliate.objects.filter(status=Affiliate.STATUS_ACTIVE):
            payout = aff_svc.generate_payout_batch(
                affiliate=affiliate, period_start=ps, period_end=pe,
            )
            if payout is not None:
                created.append(AffiliatePayoutSerializer(payout).data)
        return Response({"created": created, "count": len(created)})
