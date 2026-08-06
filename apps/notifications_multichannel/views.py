"""HTTP endpoints — push subscribe / unsubscribe + admin test ping."""
from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import PushSubscribeRequestSerializer
from .services import (
    send_email,
    send_push,
    send_sms,
    subscribe_push,
    unsubscribe_push,
)


class PushSubscribeView(APIView):
    """POST /api/notifications/push/subscribe/ — register a Web Push sub.

    Body matches what the browser's ``ServiceWorkerRegistration.pushManager
    .subscribe()`` resolves to, serialized via ``.toJSON()``:

    ```json
    {
      "endpoint": "https://fcm.googleapis.com/fcm/send/...",
      "keys": {"p256dh": "...", "auth": "..."}
    }
    ```
    """
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        serializer = PushSubscribeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        keys = data["keys"]
        sub = subscribe_push(
            user=request.user,
            endpoint=data["endpoint"],
            p256dh=keys["p256dh"],
            auth=keys["auth"],
            user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:255],
        )
        return Response(
            {"id": sub.pk, "endpoint": sub.endpoint},
            status=status.HTTP_201_CREATED,
        )


class PushUnsubscribeView(APIView):
    """POST /api/notifications/push/unsubscribe/ — body: ``{endpoint}``."""
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        endpoint = (request.data.get("endpoint") or "").strip()
        if not endpoint:
            return Response({"detail": "endpoint requis."}, status=400)
        unsubscribe_push(user=request.user, endpoint=endpoint)
        return Response(status=status.HTTP_204_NO_CONTENT)


class TestNotificationView(APIView):
    """POST /api/notifications/test/ — admin-only hello on all channels.

    Body (all optional):
      - ``email``: bool (default true)
      - ``push``: bool  (default true)
      - ``sms``: bool   (default false — Twilio costs $$)

    Sends to the authenticated admin user themselves so test traffic
    never reaches real customers.
    """
    permission_classes = (IsAdminUser,)

    def post(self, request: Request) -> Response:
        want_email = bool(request.data.get("email", True))
        want_push = bool(request.data.get("push", True))
        want_sms = bool(request.data.get("sms", False))

        results: dict[str, dict] = {}
        if want_email:
            r = send_email(
                user=request.user,
                role="notification",
                subject="Test notification",
                html="<p>Hello from notifications-multichannel.</p>",
                text="Hello from notifications-multichannel.",
            )
            results["email"] = {"status": r.status, "error": r.error}
        if want_push:
            r = send_push(
                user=request.user,
                title="Test notification",
                body="Hello from notifications-multichannel.",
                url="/",
            )
            results["push"] = {
                "status": r.status,
                "error": r.error,
                "delivered": r.meta.get("delivered", 0),
            }
        if want_sms:
            r = send_sms(
                user=request.user,
                body="Test from notifications-multichannel.",
            )
            results["sms"] = {"status": r.status, "error": r.error}

        return Response({"results": results})
