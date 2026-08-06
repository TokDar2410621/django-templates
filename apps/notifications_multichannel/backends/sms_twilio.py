"""SMS backend — Twilio.

Twilio's Python SDK is heavy and imports the world; we keep it lazy so a
project that doesn't need SMS doesn't pay the import cost (and doesn't
need ``twilio`` installed).

Body is auto-truncated to ``NOTIFICATIONS_SMS_MAX_LEN`` (default 320 = 2
SMS segments) to keep cost predictable.
"""
from __future__ import annotations

import logging

from django.conf import settings

from .base import SendResult

logger = logging.getLogger(__name__)

_DEFAULT_MAX_LEN = 320


def _twilio_settings() -> tuple[str, str, str]:
    sid = getattr(settings, "TWILIO_ACCOUNT_SID", "") or ""
    auth = getattr(settings, "TWILIO_AUTH_TOKEN", "") or ""
    from_num = getattr(settings, "TWILIO_FROM_NUMBER", "") or ""
    return sid, auth, from_num


def _valid_e164(number: str) -> bool:
    """Cheap E.164 sanity check — Twilio rejects non-+ numbers anyway."""
    return bool(number) and number.startswith("+") and number[1:].isdigit()


def send(*, to_e164: str, body: str) -> SendResult:
    """Send a single SMS via Twilio. Returns a SendResult."""
    sid, auth, from_num = _twilio_settings()
    if not (sid and auth and from_num):
        logger.info(
            "notifications.sms skipped (no Twilio creds) — to=%s body=%s",
            to_e164, body[:80],
        )
        return SendResult(status="skipped", error="Twilio credentials missing")

    if not _valid_e164(to_e164):
        return SendResult(
            status="failed",
            error=f"Invalid E.164 destination: {to_e164!r}",
        )

    max_len = getattr(settings, "NOTIFICATIONS_SMS_MAX_LEN", _DEFAULT_MAX_LEN)
    truncated = body[:max_len]

    try:
        from twilio.rest import Client  # type: ignore
    except ImportError as exc:  # pragma: no cover
        logger.warning("notifications.sms skipped — twilio not installed (%s)", exc)
        return SendResult(status="skipped", error="twilio package missing")

    try:
        client = Client(sid, auth)
        msg = client.messages.create(from_=from_num, to=to_e164, body=truncated)
    except Exception as exc:  # twilio raises a tree of exceptions; catch broadly
        logger.warning("notifications.sms failed to=%s exc=%s", to_e164, exc)
        return SendResult(status="failed", error=str(exc))

    return SendResult(status="sent", provider_message_id=str(msg.sid))
