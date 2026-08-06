"""HTTP endpoints — Connect OAuth, partner payouts, Stripe webhook.

URL summary (see ``urls.py`` for the full mounting):

  GET  /connect/start/           IsAuthenticated  → 302 to Stripe OAuth URL
  GET  /connect/callback/        AllowAny         → links partner, 302 to FE
  GET  /payouts/                 IsAuthenticated  → own payout history
  POST /webhooks/stripe/         AllowAny         → signed payload, 200/400

The webhook view is AllowAny on purpose — Stripe authenticates by
HMAC signature, not by session. Bad signature → 400.
"""
from __future__ import annotations

import logging

from django.core import signing
from django.http import HttpResponseRedirect
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Partner, Payout
from .selectors import get_partner_by_user, payout_history
from .serializers import (
    ConnectCallbackSerializer,
    PartnerSerializer,
    PayoutSerializer,
)
from .services import (
    PartnerNotPayable,
    StripeNotConfigured,
    connect_oauth_url,
    handle_connect_callback,
    parse_oauth_state,
)
from .webhooks import construct_event, dispatch_event

logger = logging.getLogger(__name__)


def _frontend_url() -> str:
    """Where to send the partner after OAuth completes / fails.

    Reads ``STRIPE_CONNECT_RETURN_URL`` first (project-specific landing
    page), falls back to ``FRONTEND_URL`` if present.
    """
    from django.conf import settings

    return (
        getattr(settings, "STRIPE_CONNECT_RETURN_URL", "")
        or getattr(settings, "FRONTEND_URL", "")
        or ""
    ).rstrip("/")


class PartnerConnectStartView(APIView):
    """GET /connect/start/

    Builds the Stripe OAuth URL for the current user's Partner profile
    and returns it. The frontend pops it open (full-page redirect or
    new tab) so the partner can authorize their existing Stripe account.

    Returns:
      200 ``{"url": "https://connect.stripe.com/oauth/authorize?..."}``
      403 if the user has no Partner profile
      503 if Stripe isn't configured
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        partner = get_partner_by_user(request.user)
        if partner is None:
            return Response(
                {"detail": "No partner profile for this user."},
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            url = connect_oauth_url(partner)
        except StripeNotConfigured as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({"url": url})


class PartnerConnectCallbackView(APIView):
    """GET/POST /connect/callback/

    The redirect URI registered on the Stripe dashboard. Stripe sends:

      ``?code=ac_xxx&state=<signed>``  on success
      ``?error=access_denied&state=…`` on user cancel

    On success we exchange ``code`` for the partner's ``acct_xxx`` and
    stamp the row, then redirect to ``STRIPE_CONNECT_RETURN_URL`` with
    a status query param the frontend can read.
    """

    permission_classes = (AllowAny,)
    authentication_classes = ()

    def get(self, request: Request) -> Response:
        return self._handle(request)

    # Stripe uses GET, but some test harnesses POST — accept both.
    def post(self, request: Request) -> Response:
        return self._handle(request)

    def _handle(self, request: Request) -> Response:
        params = (
            ConnectCallbackSerializer(data=request.query_params)
            if request.method == "GET"
            else ConnectCallbackSerializer(data=request.data)
        )
        params.is_valid(raise_exception=False)
        code = (params.validated_data.get("code") or "").strip()
        state = (params.validated_data.get("state") or "").strip()
        oauth_error = (params.validated_data.get("error") or "").strip()
        fe = _frontend_url()

        if oauth_error:
            target = (
                f"{fe}/connect/result?status=cancelled&reason={oauth_error}"
                if fe else None
            )
            if target:
                return HttpResponseRedirect(target)
            return Response(
                {"status": "cancelled", "reason": oauth_error},
                status=status.HTTP_200_OK,
            )

        if not code or not state:
            return Response(
                {"detail": "Missing code or state."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            partner_pk = parse_oauth_state(state)
        except signing.SignatureExpired:
            return Response(
                {"detail": "OAuth link expired — request a new one."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except signing.BadSignature:
            logger.warning("scm.connect.bad_state state=%s", state[:40])
            return Response(
                {"detail": "Invalid OAuth state."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            partner = Partner.objects.get(pk=partner_pk)
        except Partner.DoesNotExist:
            return Response(
                {"detail": "Partner not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            handle_connect_callback(code=code, partner=partner)
        except StripeNotConfigured as exc:
            logger.error("scm.connect.not_configured: %s", exc)
            return Response(
                {"detail": "Stripe not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as exc:  # stripe errors + network
            logger.exception(
                "scm.connect.exchange_failed partner=%s", partner_pk,
            )
            return Response(
                {"detail": f"OAuth exchange failed: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        if fe:
            return HttpResponseRedirect(
                f"{fe}/connect/result?status=ok&partner={partner_pk}"
            )
        return Response(
            PartnerSerializer(partner).data,
            status=status.HTTP_200_OK,
        )


class PartnerPayoutsView(APIView):
    """GET /payouts/

    Returns the authenticated partner's own payout history (newest first).
    Auth is the user's session/token; the lookup is by user → Partner.
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        partner = get_partner_by_user(request.user)
        if partner is None:
            return Response(
                {"detail": "No partner profile for this user."},
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            limit = int(request.query_params.get("limit", "100"))
        except ValueError:
            limit = 100
        limit = max(1, min(limit, 500))
        qs = payout_history(partner, limit=limit)
        return Response(PayoutSerializer(qs, many=True).data)


class StripeWebhookView(APIView):
    """POST /webhooks/stripe/

    Stripe-signed payload. Returns 200 on success, 400 on signature
    failure, 503 if the webhook secret isn't configured. Body of the
    response is intentionally minimal — Stripe only checks the status.
    """

    permission_classes = (AllowAny,)
    authentication_classes = ()

    def post(self, request: Request) -> Response:
        sig = request.META.get("HTTP_STRIPE_SIGNATURE", "")
        if not sig:
            return Response(
                {"detail": "Missing Stripe-Signature header."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            event = construct_event(request.body, sig)
        except RuntimeError:
            return Response(
                {"detail": "Webhook secret not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as exc:  # stripe.SignatureVerificationError etc.
            logger.warning("scm.webhook.bad_signature: %s", exc)
            return Response(
                {"detail": "Invalid signature."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            handled = dispatch_event(event)
        except Exception:  # pragma: no cover — defensive
            logger.exception(
                "scm.webhook.handler_crashed event_type=%s",
                event.get("type"),
            )
            # Return 200 so Stripe doesn't keep retrying a broken
            # handler. The error is logged for an operator to fix.
            return Response({"received": True, "handled": False})

        return Response({"received": True, "handled": bool(handled)})


# Payout retry endpoint isn't exposed by default — admins can re-run
# ``create_payout(partner=…, …)`` from a custom admin action. Surface
# it as a view in your project if you want a self-serve UI.

# Suppress unused-import warning — kept for re-export convenience.
_ = Payout
