"""Web Push backend — pywebpush + VAPID.

Sends one push payload to ALL of a user's registered subscriptions.
Dead subscriptions (HTTP 410 from the push service) are auto-pruned so
the table doesn't accumulate stale rows after browser uninstalls.

Degraded mode: missing VAPID keys → log + return ``status='skipped'``.
"""
from __future__ import annotations

import json
import logging
from typing import Iterable, Optional

from django.conf import settings
from django.utils import timezone

from ..models import PushSubscription
from .base import SendResult

logger = logging.getLogger(__name__)


def _unwrap_pem(value: str) -> str:
    """Un-escape literal ``\\n`` in a single-line env-var PEM block.

    Railway / Heroku style env-var inputs collapse newlines; we accept the
    convention of pasting ``-----BEGIN ...\\n...-----END ...`` and restore
    the real newlines at runtime.
    """
    if not value:
        return ""
    return value.replace("\\n", "\n")


def _vapid_settings() -> tuple[str, str, str]:
    pub = getattr(settings, "VAPID_PUBLIC_KEY", "") or ""
    priv = _unwrap_pem(getattr(settings, "VAPID_PRIVATE_KEY", "") or "")
    admin_email = getattr(settings, "VAPID_ADMIN_EMAIL", "") or ""
    return pub, priv, admin_email


def send(
    *,
    user,
    title: str,
    body: str,
    url: str = "/",
    icon: Optional[str] = None,
    subscriptions: Optional[Iterable[PushSubscription]] = None,
    ttl: int = 24 * 3600,
) -> SendResult:
    """Push to every subscription belonging to ``user``.

    ``subscriptions`` can be passed explicitly (e.g. pre-filtered queryset)
    — otherwise we fetch them from the relation.

    Returns a SendResult whose ``meta`` carries:
      - ``delivered``: int — count of successful pushes
      - ``pruned``:    int — count of 410-gone subscriptions removed
    """
    pub, priv, admin_email = _vapid_settings()
    if not pub or not priv:
        logger.info(
            "notifications.push skipped (no VAPID keys) — user=%s title=%s",
            getattr(user, "pk", None), title,
        )
        return SendResult(
            status="skipped",
            error="VAPID keys not configured",
            meta={"delivered": 0, "pruned": 0},
        )
    if not admin_email:
        logger.warning("notifications.push skipped — VAPID_ADMIN_EMAIL required")
        return SendResult(
            status="skipped",
            error="VAPID_ADMIN_EMAIL required",
            meta={"delivered": 0, "pruned": 0},
        )

    # Import pywebpush lazily so the package can be uninstalled in environ-
    # ments that don't need push without breaking Django boot.
    try:
        from pywebpush import WebPushException, webpush  # type: ignore
    except ImportError as exc:  # pragma: no cover
        logger.warning("notifications.push skipped — pywebpush not installed (%s)", exc)
        return SendResult(
            status="skipped",
            error="pywebpush package missing",
            meta={"delivered": 0, "pruned": 0},
        )

    if subscriptions is None:
        subscriptions = list(user.push_subscriptions.all())

    payload = json.dumps({
        "title": title,
        "body": body,
        "url": url,
        "icon": icon or getattr(settings, "NOTIFICATIONS_PUSH_DEFAULT_ICON",
                               "/static/icons/192.png"),
    })

    delivered = 0
    dead_ids: list[int] = []
    last_error = ""
    used_ids: list[int] = []

    for sub in subscriptions:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=payload,
                vapid_private_key=priv,
                vapid_claims={"sub": f"mailto:{admin_email}"},
                ttl=ttl,
            )
            delivered += 1
            used_ids.append(sub.pk)
        except WebPushException as exc:
            response = getattr(exc, "response", None)
            code = getattr(response, "status_code", None)
            if code == 410:
                dead_ids.append(sub.pk)
                logger.info("notifications.push removing expired sub=%s", sub.pk)
            else:
                last_error = f"HTTP {code}: {exc}"
                logger.warning(
                    "notifications.push failed sub=%s code=%s exc=%s",
                    sub.pk, code, exc,
                )

    if dead_ids:
        PushSubscription.objects.filter(pk__in=dead_ids).delete()
    if used_ids:
        PushSubscription.objects.filter(pk__in=used_ids).update(
            last_used_at=timezone.now(),
        )

    if delivered:
        return SendResult(
            status="sent",
            meta={"delivered": delivered, "pruned": len(dead_ids)},
        )
    if last_error:
        return SendResult(
            status="failed",
            error=last_error,
            meta={"delivered": 0, "pruned": len(dead_ids)},
        )
    # No subscriptions to send to, or only 410-gone ones.
    return SendResult(
        status="skipped",
        error="No active push subscriptions",
        meta={"delivered": 0, "pruned": len(dead_ids)},
    )
