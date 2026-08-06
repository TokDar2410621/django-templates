"""DRF views — subscription read, checkout creation, Stripe webhook.

Auth model:
- ``MeSubscriptionView`` is IsAuthenticated.
- ``StripeCheckoutView`` is IsAuthenticated (user must be logged in to buy).
- ``StripeWebhookView`` has NO auth: it's verified by Stripe's HMAC
  signature header instead.

Degraded mode: if ``STRIPE_SECRET_KEY`` or ``STRIPE_WEBHOOK_SECRET`` are
missing, the relevant endpoints return 503 instead of crashing on import.
The rest of the app keeps working.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from django.conf import settings
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .exceptions import InvalidPlan, QuotaExceeded
from .selectors import (
    get_balance,
    get_or_create_subscription,
    recent_transactions,
)
from .serializers import (
    CheckoutSerializer,
    ConsumeSerializer,
    CreditTransactionSerializer,
    SubscriptionSerializer,
)
from .services import attach_stripe_customer, consume
from .webhooks import dispatch as dispatch_stripe_event

logger = logging.getLogger(__name__)


def _stripe_or_503() -> tuple[Any, str | None, str | None]:
    """Return ``(stripe_module, secret, webhook_secret)`` or 503 if unconfigured.

    Imports the stripe SDK lazily so the app boots without the dependency
    installed (you still need it to actually charge people).
    """
    secret = os.environ.get("STRIPE_SECRET_KEY")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
    if not secret:
        return None, None, None
    try:
        import stripe  # type: ignore[import-not-found]
    except ImportError:
        logger.error("stripe SDK not installed; pip install stripe>=10")
        return None, None, None
    stripe.api_key = secret
    return stripe, secret, webhook_secret


class MeSubscriptionView(APIView):
    """GET ``/me/`` → current user's subscription + balance + recent txns."""

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        sub = get_or_create_subscription(request.user)
        txns = recent_transactions(request.user, n=20)
        return Response({
            "subscription": SubscriptionSerializer(sub).data,
            "balance": get_balance(request.user),
            "recent_transactions": CreditTransactionSerializer(txns, many=True).data,
        })


class ConsumeView(APIView):
    """POST ``/consume/`` ``{resource_key, n=1}`` → bucket used (``"quota"``/``"credit"``).

    Returns 402 Payment Required when both buckets are exhausted. Frontend
    should react by surfacing the credits-purchase CTA.
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        ser = ConsumeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            bucket = consume(
                request.user,
                ser.validated_data["resource_key"],
                n=ser.validated_data["n"],
            )
        except QuotaExceeded as exc:
            return Response(
                {
                    "error": "quota_exceeded",
                    "resource_key": exc.resource_key,
                    "plan_limit": exc.plan_limit,
                    "current_count": exc.current_count,
                    "credits_available": exc.credits_available,
                    "requested": exc.requested,
                    "detail": str(exc),
                },
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )
        except InvalidPlan as exc:
            return Response(
                {"error": "invalid_plan", "detail": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        sub = get_or_create_subscription(request.user)
        return Response({
            "bucket": bucket,
            "plan": sub.plan,
            "balance": get_balance(request.user),
        })


class StripeCheckoutView(APIView):
    """POST ``/checkout/`` ``{mode, sku}`` → Stripe Checkout URL.

    ``mode="subscription"`` + ``sku=<plan slug>`` → recurring sub.
    ``mode="payment"``     + ``sku=<pack slug>`` → one-time credits pack.
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        ser = CheckoutSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        mode = ser.validated_data["mode"]
        sku = ser.validated_data["sku"]

        stripe_mod, _secret, _ = _stripe_or_503()
        if stripe_mod is None:
            return Response(
                {"error": "STRIPE_SECRET_KEY not configured"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if mode == "subscription":
            return self._subscription_checkout(request, stripe_mod, sku)
        return self._payment_checkout(request, stripe_mod, sku)

    # -- subscription mode -------------------------------------------------

    def _subscription_checkout(self, request, stripe_mod, plan_slug: str) -> Response:
        prices: dict[str, str] = getattr(settings, "SAAS_PLAN_STRIPE_PRICES", {})
        env_var = prices.get(plan_slug)
        if not env_var:
            raise ValidationError(
                {"sku": f"Plan '{plan_slug}' has no Stripe price configured."},
            )
        price_id = os.environ.get(env_var)
        if not price_id:
            return Response(
                {"error": f"{env_var} env var not set"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        sub = get_or_create_subscription(request.user)
        if not sub.stripe_customer_id:
            try:
                customer = stripe_mod.Customer.create(
                    email=getattr(request.user, "email", None) or None,
                    name=str(request.user),
                    metadata={"user_id": str(request.user.pk)},
                )
            except Exception as exc:  # pragma: no cover - network
                logger.exception("Stripe Customer.create failed")
                return Response(
                    {"error": f"Stripe error: {str(exc)[:120]}"},
                    status=status.HTTP_502_BAD_GATEWAY,
                )
            sub = attach_stripe_customer(request.user, customer.id)

        success, cancel = _success_cancel_urls(suffix="?status=success", cancel_suffix="?status=cancel")
        try:
            session = stripe_mod.checkout.Session.create(
                customer=sub.stripe_customer_id,
                mode="subscription",
                line_items=[{"price": price_id, "quantity": 1}],
                success_url=success,
                cancel_url=cancel,
                allow_promotion_codes=True,
                metadata={"user_id": str(request.user.pk), "plan": plan_slug},
                subscription_data={
                    "metadata": {"user_id": str(request.user.pk), "plan": plan_slug},
                },
            )
        except Exception as exc:  # pragma: no cover - network
            logger.exception("Stripe checkout subscription failed")
            return Response(
                {"error": f"Stripe error: {str(exc)[:120]}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response({"url": session.url, "session_id": session.id})

    # -- payment (credits) mode --------------------------------------------

    def _payment_checkout(self, request, stripe_mod, pack_slug: str) -> Response:
        packs: dict[str, dict[str, Any]] = getattr(settings, "SAAS_CREDIT_PACKS", {})
        if pack_slug not in packs:
            raise ValidationError(
                {"sku": f"Pack '{pack_slug}' not in SAAS_CREDIT_PACKS."},
            )
        pack = packs[pack_slug]
        env_var = pack.get("env")
        if not env_var:
            raise ValidationError(
                {"sku": f"Pack '{pack_slug}' missing 'env' in SAAS_CREDIT_PACKS."},
            )
        price_id = os.environ.get(env_var)
        if not price_id:
            return Response(
                {"error": f"{env_var} env var not set"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        sub = get_or_create_subscription(request.user)
        success, cancel = _success_cancel_urls(
            suffix="?credits=success", cancel_suffix="?credits=cancel",
        )
        kwargs: dict[str, Any] = dict(
            mode="payment",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success,
            cancel_url=cancel,
            metadata={
                "user_id": str(request.user.pk),
                "pack": pack_slug,
                "credits": str(pack["credits"]),
            },
        )
        if sub.stripe_customer_id:
            kwargs["customer"] = sub.stripe_customer_id
        elif getattr(request.user, "email", None):
            kwargs["customer_email"] = request.user.email
        try:
            session = stripe_mod.checkout.Session.create(**kwargs)
        except Exception as exc:  # pragma: no cover - network
            logger.exception("Stripe checkout payment failed")
            return Response(
                {"error": f"Stripe error: {str(exc)[:120]}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response({"url": session.url, "session_id": session.id})


def _success_cancel_urls(*, suffix: str, cancel_suffix: str) -> tuple[str, str]:
    base = (
        os.environ.get("FRONTEND_BASE_URL")
        or getattr(settings, "FRONTEND_BASE_URL", "")
        or "http://localhost:3000"
    ).rstrip("/")
    path = getattr(settings, "SAAS_CHECKOUT_RETURN_PATH", "/billing")
    return (f"{base}{path}{suffix}", f"{base}{path}{cancel_suffix}")


class StripeWebhookView(APIView):
    """POST ``/stripe/webhook/`` — Stripe HMAC-verified event ingestion.

    Always returns 200 once the signature passes, even if the inner dispatch
    crashes, so Stripe doesn't enter retry-storm on a handler bug we own.
    """

    permission_classes = (AllowAny,)
    authentication_classes = ()

    def post(self, request: Request) -> Response:
        stripe_mod, _secret, webhook_secret = _stripe_or_503()
        if stripe_mod is None or not webhook_secret:
            return Response(
                {"error": "Stripe webhook not configured"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
        payload = request.body
        try:
            event = stripe_mod.Webhook.construct_event(
                payload, sig_header, webhook_secret,
            )
        except Exception as exc:
            logger.warning("Stripe webhook signature invalid: %s", exc)
            return Response(
                {"error": "invalid signature"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # `event` from the SDK behaves like a dict for our purposes.
        event_id = event.get("id")
        event_type = event.get("type")
        logger.info(
            "saas.webhook received id=%s type=%s", event_id, event_type,
        )
        try:
            dispatch_stripe_event(event)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception(
                "saas.webhook dispatch crashed id=%s type=%s: %s",
                event_id, event_type, exc,
            )
        return Response({"received": True})
