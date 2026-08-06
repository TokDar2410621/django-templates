"""DRF views for newsletter_engine.

Three surfaces:

1. **Admin/internal API** — ``IsAuthenticated``. ViewSets for Subscriber,
   MailingList, Tag, Segment, Campaign, Automation. Tenant scoping is via
   ``_resolve_tenant(request)`` — defaults to ``request.user`` but can be
   overridden by ``NEWSLETTER_TENANT_RESOLVER``.

2. **Public** — no auth. Subscribe, confirm, unsubscribe, preferences.
   These don't leak whether an email exists — POST /subscribe/ always
   returns 200 with a generic "check your inbox" message.

3. **Tracking** — no auth. Pixel + click-redirect, hit from mail clients.

4. **Webhooks** — no auth, verified by Resend signature.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from typing import Any, Optional

from django.conf import settings
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.utils.module_loading import import_string
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .exceptions import (
    CampaignStateError,
    SegmentDSLError,
    SubscriberConflict,
    UnsubscribeTokenInvalid,
)
from .models import (
    Automation,
    BounceEvent,
    Campaign,
    Delivery,
    MailingList,
    Membership,
    Segment,
    Subscriber,
    Tag,
)
from .selectors import (
    campaign_delivery_status,
    get_subscriber_by_token,
    get_token,
)
from .serializers import (
    AutomationSerializer,
    CampaignSerializer,
    CampaignStatsSerializer,
    MailingListSerializer,
    PublicPreferencesUpdateSerializer,
    PublicSubscribeSerializer,
    SegmentPreviewSerializer,
    SegmentSerializer,
    SubscriberSerializer,
    TagSerializer,
)
from .services import (
    cache_segment_count,
    cancel_campaign,
    confirm_subscriber,
    evaluate_segment,
    mark_bounced,
    record_click,
    record_open,
    send_campaign,
    subscribe as svc_subscribe,
    unsubscribe as svc_unsubscribe,
)

logger = logging.getLogger(__name__)


# ===========================================================================
# Tenant resolution
# ===========================================================================
def _resolve_tenant(request: Request) -> Any:
    """Return the tenant for this request.

    Default: ``request.user``. Override via
    ``NEWSLETTER_TENANT_RESOLVER`` setting (dotted path to a callable that
    takes a request and returns the tenant model instance).
    """
    dotted = getattr(settings, "NEWSLETTER_TENANT_RESOLVER", "")
    if dotted:
        resolver = import_string(dotted)
        return resolver(request)
    return request.user


# ===========================================================================
# Admin viewsets
# ===========================================================================
class _TenantScopedViewSet(viewsets.ModelViewSet):
    """Base for viewsets that filter by tenant on every read + auto-set
    tenant on every write.

    Override ``model`` and ``serializer_class`` in subclasses.
    """

    permission_classes = (IsAuthenticated,)
    model: Any = None

    def get_queryset(self):
        tenant = _resolve_tenant(self.request)
        return self.model.objects.filter(tenant=tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=_resolve_tenant(self.request))


class SubscriberViewSet(_TenantScopedViewSet):
    model = Subscriber
    serializer_class = SubscriberSerializer

    @action(detail=False, methods=["post"], url_path="bulk-add-to-list")
    def bulk_add_to_list(self, request: Request) -> Response:
        """Body: ``{subscriber_ids: [..], list_id: <int>}``."""
        from .services.subscribers import add_to_list
        ids = request.data.get("subscriber_ids") or []
        list_id = request.data.get("list_id")
        if not isinstance(ids, list) or list_id is None:
            return Response(
                {"detail": "subscriber_ids and list_id required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        tenant = _resolve_tenant(request)
        ml = get_object_or_404(MailingList, pk=list_id, tenant=tenant)
        count = 0
        for sub in Subscriber.objects.filter(tenant=tenant, pk__in=ids):
            add_to_list(sub, ml)
            count += 1
        return Response({"count": count})


class MailingListViewSet(_TenantScopedViewSet):
    model = MailingList
    serializer_class = MailingListSerializer


class TagViewSet(_TenantScopedViewSet):
    model = Tag
    serializer_class = TagSerializer


class SegmentViewSet(_TenantScopedViewSet):
    model = Segment
    serializer_class = SegmentSerializer

    def perform_create(self, serializer):
        seg = serializer.save(tenant=_resolve_tenant(self.request))
        # Compute the cached count right away so the admin sees a value.
        try:
            cache_segment_count(seg)
        except SegmentDSLError as exc:
            logger.warning("newsletter.segment.dsl_error on create: %s", exc)

    def perform_update(self, serializer):
        seg = serializer.save()
        try:
            cache_segment_count(seg)
        except SegmentDSLError as exc:
            logger.warning("newsletter.segment.dsl_error on update: %s", exc)

    @action(detail=True, methods=["get"], url_path="preview")
    def preview(self, request: Request, pk=None) -> Response:
        seg = self.get_object()
        try:
            qs = evaluate_segment(seg)
        except SegmentDSLError as exc:
            return Response(
                {"error": "invalid_dsl", "detail": exc.reason, "node": exc.node},
                status=status.HTTP_400_BAD_REQUEST,
            )
        count = qs.count()
        sample = list(qs[:25])
        data = SegmentPreviewSerializer(
            {"count": count, "sample": sample},
        ).data
        return Response(data)


class CampaignViewSet(_TenantScopedViewSet):
    model = Campaign
    serializer_class = CampaignSerializer

    def perform_create(self, serializer):
        serializer.save(
            tenant=_resolve_tenant(self.request),
            created_by=self.request.user if self.request.user.is_authenticated else None,
        )

    @action(detail=True, methods=["post"], url_path="send")
    def send(self, request: Request, pk=None) -> Response:
        camp = self.get_object()
        try:
            send_campaign(camp)
        except CampaignStateError as exc:
            return Response(
                {"error": "invalid_state", "detail": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(self.get_serializer(camp).data)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request: Request, pk=None) -> Response:
        camp = self.get_object()
        reason = (request.data.get("reason") or "")[:200]
        cancel_campaign(camp, reason=reason)
        return Response(self.get_serializer(camp).data)

    @action(detail=True, methods=["get"], url_path="stats")
    def stats(self, request: Request, pk=None) -> Response:
        camp = self.get_object()
        by_status = campaign_delivery_status(camp)
        out = {
            "by_status": by_status,
            "sent_count": camp.sent_count,
            "open_count": camp.open_count,
            "click_count": camp.click_count,
            "bounce_count": camp.bounce_count,
            "complaint_count": camp.complaint_count,
        }
        return Response(CampaignStatsSerializer(out).data)


class AutomationViewSet(_TenantScopedViewSet):
    model = Automation
    serializer_class = AutomationSerializer


# ===========================================================================
# Public endpoints (no auth)
# ===========================================================================
class _PublicMixin:
    permission_classes = (AllowAny,)
    authentication_classes = ()


class SubscribeView(_PublicMixin, APIView):
    """POST /api/newsletter/subscribe/

    Body: ``{email, list_slug?, name?, locale?, consented_marketing, source?}``

    Tenant resolution for unauthenticated public requests:
      - If ``NEWSLETTER_TENANT_RESOLVER`` is set, it's called with the request
        (and can resolve via host/header/etc).
      - Otherwise, we look at the ``list_slug``: a MailingList with that
        slug uniquely identifies the tenant when slugs are globally unique
        in single-tenant deployments (the common case for this template
        when ``NEWSLETTER_TENANT_MODEL`` == AUTH_USER_MODEL).

    Always returns 200 with a generic "check your inbox" message — we don't
    leak whether the email exists.
    """

    def post(self, request: Request) -> Response:
        ser = PublicSubscribeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        payload = ser.validated_data

        list_slug = (payload.get("list_slug") or "").strip()
        ml: Optional[MailingList] = None
        tenant = None
        if list_slug:
            ml = MailingList.objects.filter(slug=list_slug, is_active=True).first()
            if ml is None:
                # Generic 200 — don't leak which slugs exist.
                return Response({"ok": True, "detail": "Subscription requested."})
            tenant = ml.tenant
        else:
            # Try the resolver; if none configured, refuse with 400 because
            # we have no way to scope the subscriber.
            try:
                tenant = _resolve_tenant(request)
            except Exception:
                return Response(
                    {"ok": False, "detail": "list_slug required."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        try:
            sub, token = svc_subscribe(
                tenant=tenant,
                email=payload["email"],
                name=payload.get("name") or "",
                list=ml,
                source=payload.get("source") or "public",
                locale=payload.get("locale") or "fr",
                consented=bool(payload.get("consented_marketing")),
            )
        except SubscriberConflict:
            # Don't leak — still 200.
            return Response({"ok": True, "detail": "Subscription requested."})

        # Hook for projects that want to send the confirmation email themselves
        # immediately — log the token so they can grep for it in tests.
        if token is not None:
            logger.info(
                "newsletter.subscribe confirm_token sub=%s token=%s",
                sub.pk, token.token[:10] + "…",
            )

        return Response({"ok": True, "detail": "Subscription requested."})


class ConfirmView(_PublicMixin, APIView):
    """GET /api/newsletter/confirm/?token=..."""

    def get(self, request: Request) -> Response:
        token = request.GET.get("token", "")
        try:
            sub = confirm_subscriber(token)
        except UnsubscribeTokenInvalid:
            return Response(
                {"ok": False, "detail": "Invalid or expired confirmation token."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Optional redirect target.
        redirect_url = getattr(settings, "NEWSLETTER_CONFIRM_REDIRECT_URL", "")
        if redirect_url:
            return HttpResponseRedirect(redirect_url)
        return Response({"ok": True, "email": sub.email, "status": sub.status})


class UnsubscribeView(_PublicMixin, APIView):
    """GET (or POST) /api/newsletter/unsubscribe/?token=...&scope=...

    RFC 8058 mandates POST support for one-click. We accept both verbs.
    """

    def _do(self, request: Request) -> Response:
        token = request.GET.get("token") or request.data.get("token") or ""
        scope = request.GET.get("scope") or request.data.get("scope") or None
        try:
            sub = svc_unsubscribe(token, scope_override=scope)
        except UnsubscribeTokenInvalid as exc:
            return Response(
                {"ok": False, "detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        redirect_url = getattr(settings, "NEWSLETTER_UNSUBSCRIBE_REDIRECT_URL", "")
        if redirect_url:
            return HttpResponseRedirect(redirect_url)
        return Response({"ok": True, "email": sub.email, "status": sub.status})

    def get(self, request: Request) -> Response:
        return self._do(request)

    def post(self, request: Request) -> Response:
        return self._do(request)


class PreferencesView(_PublicMixin, APIView):
    """GET ?token=...    -> list which lists the subscriber is on
       POST {token, list_slugs}  -> update memberships (keep only listed)
    """

    def get(self, request: Request) -> Response:
        token = request.GET.get("token", "")
        sub = get_subscriber_by_token(token)
        if sub is None:
            return Response(
                {"ok": False, "detail": "Invalid token"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        memberships = (
            Membership.objects
            .filter(subscriber=sub)
            .select_related("list")
        )
        return Response({
            "ok": True,
            "email": sub.email,
            "memberships": [
                {
                    "list_slug": m.list.slug,
                    "list_name": m.list.name,
                    "status": m.status,
                }
                for m in memberships
            ],
        })

    def post(self, request: Request) -> Response:
        ser = PublicPreferencesUpdateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        sub = get_subscriber_by_token(ser.validated_data["token"])
        if sub is None:
            return Response(
                {"ok": False, "detail": "Invalid token"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        wanted = set(ser.validated_data["list_slugs"])
        from .services.subscribers import add_to_list, remove_from_list
        # Unsubscribe from anything not in wanted, subscribe (or re-activate)
        # anything in wanted.
        current = Membership.objects.filter(subscriber=sub).select_related("list")
        current_by_slug = {m.list.slug: m for m in current}
        # Remove
        for slug, m in current_by_slug.items():
            if slug not in wanted and m.status == Membership.STATUS_ACTIVE:
                remove_from_list(sub, m.list, reason="self-service preferences")
        # Add
        for slug in wanted:
            ml = MailingList.objects.filter(slug=slug, tenant=sub.tenant).first()
            if ml is not None:
                add_to_list(sub, ml)
        return Response({"ok": True})


# ===========================================================================
# Tracking endpoints (no auth)
# ===========================================================================
# 1x1 transparent GIF — embedded so we don't need a static file dep.
_TRANSPARENT_GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!"
    b"\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01"
    b"\x00\x00\x02\x02D\x01\x00;"
)


class TrackOpenView(_PublicMixin, APIView):
    """GET /track/open/<delivery_token>.gif — record open + return 1x1 GIF."""

    def get(self, request: Request, delivery_token: str) -> HttpResponse:
        delivery = Delivery.objects.filter(tracking_token=delivery_token).first()
        if delivery is not None:
            try:
                record_open(delivery)
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("newsletter.track.open recording failed: %s", exc)
        resp = HttpResponse(_TRANSPARENT_GIF, content_type="image/gif")
        resp["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return resp


class TrackClickView(_PublicMixin, APIView):
    """GET /track/click/<delivery_token>/?u=<base64-url> — record + 302."""

    def get(self, request: Request, delivery_token: str) -> HttpResponse:
        from .services.tracking import decode_click_url
        encoded = request.GET.get("u", "")
        original = decode_click_url(encoded)
        if not original:
            return HttpResponse("Bad link", status=400)
        delivery = Delivery.objects.filter(tracking_token=delivery_token).first()
        if delivery is not None:
            try:
                record_click(
                    delivery,
                    link_url=original,
                    user_agent=request.META.get("HTTP_USER_AGENT", ""),
                    ip=_client_ip(request),
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("newsletter.track.click recording failed: %s", exc)
        return HttpResponseRedirect(original)


def _client_ip(request: Request) -> Optional[str]:
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


# ===========================================================================
# Webhooks (Resend)
# ===========================================================================
class ResendWebhookView(_PublicMixin, APIView):
    """POST /webhooks/resend/ — Resend signature-verified webhook ingestion.

    Resend signs webhooks with HMAC-SHA256 using
    ``NEWSLETTER_RESEND_WEBHOOK_SECRET``. The header is
    ``Svix-Signature`` per the Svix convention Resend uses.

    Always returns 200 once the signature passes, even if dispatch crashes,
    so Resend doesn't enter retry-storm on a handler bug we own.
    """

    def post(self, request: Request) -> Response:
        secret = getattr(settings, "NEWSLETTER_RESEND_WEBHOOK_SECRET", "")
        if not secret:
            return Response(
                {"error": "webhook secret not configured"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        sig_header = request.META.get("HTTP_SVIX_SIGNATURE", "")
        body = request.body
        if not _verify_resend_signature(body, sig_header, secret):
            return Response(
                {"error": "invalid signature"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            event = request.data
        except Exception:
            event = {}

        try:
            _dispatch_resend_event(event)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("newsletter.webhook dispatch crashed: %s", exc)
        return Response({"received": True})


def _verify_resend_signature(body: bytes, sig_header: str, secret: str) -> bool:
    """Naive Svix-style HMAC check.

    The real Svix library does more (timestamp tolerance, multiple keys);
    we keep it minimal so the template has no extra dependency. If your
    project uses ``svix``, swap this for ``svix.webhooks.Webhook(...).verify``.
    """
    if not sig_header:
        return False
    expected = hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256,
    ).digest()
    # Svix format is "v1,<base64-digest>" possibly comma-separated for key rotation
    candidates = [s.strip() for s in sig_header.split(",")]
    for cand in candidates:
        if cand.startswith("v1,"):
            cand = cand[3:]
        try:
            got = base64.b64decode(cand)
        except Exception:
            continue
        if hmac.compare_digest(expected, got):
            return True
    return False


def _dispatch_resend_event(event: dict[str, Any]) -> None:
    """Route a Resend webhook event to the right handler."""
    event_type = event.get("type") or ""
    data = event.get("data") or {}
    msg_id = data.get("email_id") or data.get("id") or ""

    # Look up the Delivery by provider_message_id when present.
    delivery = (
        Delivery.objects.filter(provider_message_id=msg_id).select_related("subscriber").first()
        if msg_id else None
    )

    if event_type == "email.delivered":
        if delivery:
            from django.utils import timezone
            from django.db.models import F
            Delivery.objects.filter(pk=delivery.pk).update(
                status=Delivery.STATUS_DELIVERED,
                delivered_at=timezone.now(),
            )
            Campaign.objects.filter(pk=delivery.campaign_id).update(
                delivered_count=F("delivered_count") + 1,
            )
    elif event_type == "email.bounced":
        if delivery:
            mark_bounced(
                delivery.subscriber,
                kind=BounceEvent.KIND_HARD,
                payload=event,
                provider_message_id=msg_id,
            )
            Delivery.objects.filter(pk=delivery.pk).update(
                status=Delivery.STATUS_BOUNCED,
                error=(data.get("reason") or "")[:1000],
            )
            from django.db.models import F
            Campaign.objects.filter(pk=delivery.campaign_id).update(
                bounce_count=F("bounce_count") + 1,
            )
    elif event_type == "email.complained":
        if delivery:
            mark_bounced(
                delivery.subscriber,
                kind=BounceEvent.KIND_COMPLAINT,
                payload=event,
                provider_message_id=msg_id,
            )
            Delivery.objects.filter(pk=delivery.pk).update(
                status=Delivery.STATUS_COMPLAINED,
            )
            from django.db.models import F
            Campaign.objects.filter(pk=delivery.campaign_id).update(
                complaint_count=F("complaint_count") + 1,
            )
    else:
        logger.debug("newsletter.webhook ignored type=%s", event_type)
