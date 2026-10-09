"""Web Push backend: pywebpush + VAPID.

Sends one push payload to ALL of a user's registered subscriptions.
Dead subscriptions (HTTP 404 or 410 from the push service) are auto-pruned
so the table doesn't accumulate stale rows after browser uninstalls.

Degraded mode: missing VAPID keys → log + return ``status='skipped'``.
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Iterable, Optional

from django.conf import settings
from django.utils import timezone

from ..models import PushSubscription
from .base import SendResult

logger = logging.getLogger(__name__)

# Codes a push service returns for a subscription that no longer exists.
GONE_STATUS_CODES = (404, 410)


def _unwrap_pem(value: str) -> str:
    """Un-escape literal ``\\n`` in a single-line env-var PEM block.

    Railway / Heroku style env-var inputs collapse newlines; we accept the
    convention of pasting ``-----BEGIN ...\\n...-----END ...`` and restore
    the real newlines at runtime.
    """
    if not value:
        return ""
    return value.replace("\\n", "\n")


def private_key_for_pywebpush(value: str) -> str:
    """Return the VAPID private key in the raw base64url form pywebpush reads.

    pywebpush does NOT accept a PEM key passed as a string: it base64-decodes
    it and fails with "Could not deserialize key data". A PEM key (multi-line,
    or single-line with literal ``\\n``) is converted to the raw 32-byte
    scalar; a raw or DER base64 key is returned unchanged.

    Raises ``ValueError`` when the PEM block cannot be parsed.
    """
    value = _unwrap_pem((value or "").strip())
    if "BEGIN" not in value:
        return value
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = serialization.load_pem_private_key(value.encode("utf-8"), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise ValueError("VAPID private key must be an EC P-256 key")
    raw = key.private_numbers().private_value.to_bytes(32, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _vapid_settings() -> tuple[str, str, str]:
    pub = getattr(settings, "VAPID_PUBLIC_KEY", "") or ""
    priv = getattr(settings, "VAPID_PRIVATE_KEY", "") or ""
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

    ``subscriptions`` can be passed explicitly (e.g. pre-filtered queryset);
    otherwise we fetch them from the relation.

    Returns a SendResult whose ``meta`` carries:
      - ``delivered``: int, count of successful pushes
      - ``pruned``:    int, count of gone (404 / 410) subscriptions removed
    """
    pub, priv, admin_email = _vapid_settings()
    if not pub or not priv:
        logger.info(
            "notifications.push skipped (no VAPID keys) user=%s title=%s",
            getattr(user, "pk", None), title,
        )
        return SendResult(
            status="skipped",
            error="VAPID keys not configured",
            meta={"delivered": 0, "pruned": 0},
        )
    if not admin_email:
        logger.warning("notifications.push skipped: VAPID_ADMIN_EMAIL required")
        return SendResult(
            status="skipped",
            error="VAPID_ADMIN_EMAIL required",
            meta={"delivered": 0, "pruned": 0},
        )
    try:
        private_key = private_key_for_pywebpush(priv)
    except ValueError as exc:
        logger.error("notifications.push failed: VAPID private key unreadable (%s)", type(exc).__name__)
        return SendResult(
            status="failed",
            error="VAPID private key unreadable",
            meta={"delivered": 0, "pruned": 0},
        )

    # Import pywebpush lazily so the package can be uninstalled in environ-
    # ments that don't need push without breaking Django boot.
    try:
        from pywebpush import WebPushException, webpush  # type: ignore
    except ImportError as exc:  # pragma: no cover
        logger.warning("notifications.push skipped: pywebpush not installed (%s)", exc)
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
                vapid_private_key=private_key,
                # A fresh dict on every call: pywebpush writes the push
                # service address ("aud") into it. Shared across calls, it
                # would keep the first browser's and others would answer 403.
                vapid_claims={"sub": f"mailto:{admin_email}"},
                ttl=ttl,
            )
            delivered += 1
            used_ids.append(sub.pk)
        except WebPushException as exc:
            response = getattr(exc, "response", None)
            code = getattr(response, "status_code", None)
            if code in GONE_STATUS_CODES:
                dead_ids.append(sub.pk)
                logger.info("notifications.push removing expired sub=%s (HTTP %s)", sub.pk, code)
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
    # No subscriptions to send to, or only gone ones.
    return SendResult(
        status="skipped",
        error="No active push subscriptions",
        meta={"delivered": 0, "pruned": len(dead_ids)},
    )
