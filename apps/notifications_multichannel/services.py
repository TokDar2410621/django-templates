"""Service layer for multichannel notifications.

Public facade — callers import from here, never from the backends.

The functions below catch all provider errors and translate them into
``SendResult`` objects, then write a ``NotificationLog`` row when
``settings.NOTIFICATIONS_LOG_DELIVERIES`` is truthy (default: True).

Channel routing:
  - ``send_email(user, role, ...)`` — Resend
  - ``send_push(user, ...)``        — pywebpush
  - ``send_sms(user, ...)``         — Twilio
  - ``send(user, channel, ...)``    — generic dispatcher
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

from django.conf import settings
from django.template import TemplateDoesNotExist
from django.template.loader import render_to_string

from .backends import SendResult
from .backends import email_resend, push_webpush, sms_twilio
from .models import NotificationLog, PushSubscription

logger = logging.getLogger(__name__)

CHANNEL_EMAIL = "email"
CHANNEL_PUSH = "push"
CHANNEL_SMS = "sms"
VALID_CHANNELS = {CHANNEL_EMAIL, CHANNEL_PUSH, CHANNEL_SMS}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _logging_enabled() -> bool:
    return bool(getattr(settings, "NOTIFICATIONS_LOG_DELIVERIES", True))


def _log(
    *,
    user,
    channel: str,
    result: SendResult,
    subject: str = "",
    target: str = "",
) -> Optional[NotificationLog]:
    if not _logging_enabled():
        return None
    try:
        return NotificationLog.objects.create(
            user=user if user is not None and getattr(user, "pk", None) else None,
            channel=channel,
            status=result.status,
            subject=subject[:255],
            target=target[:320],
            provider_message_id=result.provider_message_id[:255],
            error=result.error or "",
        )
    except Exception as exc:  # pragma: no cover — never let logging crash the send
        logger.warning("notifications.log persistence failed: %s", exc)
        return None


def _render_templates(
    template_name: str,
    context: Optional[dict[str, Any]],
) -> tuple[str, Optional[str]]:
    """Render ``<name>.html`` and (optionally) ``<name>.txt``.

    The ``.txt`` variant is optional — caller's templates may omit it and
    we'll fall through to ``None``.
    """
    ctx = context or {}
    html = render_to_string(f"{template_name}.html", ctx)
    text: Optional[str]
    try:
        text = render_to_string(f"{template_name}.txt", ctx)
    except TemplateDoesNotExist:
        text = None
    return html, text


def _resolve_email(user) -> Optional[str]:
    return getattr(user, "email", None) or None


def _resolve_phone(user) -> Optional[str]:
    """Find a phone number on the user. Configurable attribute name."""
    attr = getattr(settings, "NOTIFICATIONS_USER_PHONE_ATTR", "phone_e164")
    val = getattr(user, attr, None)
    return val or None


# ---------------------------------------------------------------------------
# Public channel-specific senders
# ---------------------------------------------------------------------------
def send_email(
    *,
    user=None,
    to: Optional[str] = None,
    role: str = "notification",
    subject: str,
    html: Optional[str] = None,
    text: Optional[str] = None,
    template_name: Optional[str] = None,
    context: Optional[dict[str, Any]] = None,
    reply_to: Optional[str] = None,
) -> SendResult:
    """Send a transactional email.

    Two ways to pass the body:
      1. ``html`` (and optional ``text``)
      2. ``template_name`` + ``context`` — renders ``<name>.html`` and
         optionally ``<name>.txt`` via Django's template engine.

    Destination resolution:
      - ``to`` wins if explicit
      - otherwise we read ``user.email``
    """
    destination = (to or _resolve_email(user) or "").strip()
    if not destination:
        result = SendResult(status="failed", error="No email destination")
        _log(user=user, channel=CHANNEL_EMAIL, result=result, subject=subject)
        return result

    body_html = html
    body_text = text
    if template_name and not body_html:
        try:
            body_html, body_text = _render_templates(template_name, context)
        except Exception as exc:  # pragma: no cover — template error
            logger.exception("notifications.email template render failed")
            result = SendResult(status="failed", error=f"Template error: {exc}")
            _log(user=user, channel=CHANNEL_EMAIL, result=result,
                 subject=subject, target=destination)
            return result

    if not body_html:
        result = SendResult(status="failed", error="No body (html or template_name required)")
        _log(user=user, channel=CHANNEL_EMAIL, result=result,
             subject=subject, target=destination)
        return result

    result = email_resend.send(
        role=role,
        to=destination,
        subject=subject,
        html=body_html,
        text=body_text,
        reply_to=reply_to,
    )
    _log(user=user, channel=CHANNEL_EMAIL, result=result,
         subject=subject, target=destination)
    return result


def send_push(
    *,
    user,
    title: str,
    body: str,
    url: str = "/",
    icon: Optional[str] = None,
    subscriptions: Optional[Iterable[PushSubscription]] = None,
) -> SendResult:
    """Push to every subscription of ``user``."""
    if user is None or not getattr(user, "pk", None):
        result = SendResult(status="failed", error="user required for push")
        _log(user=None, channel=CHANNEL_PUSH, result=result, subject=title)
        return result

    result = push_webpush.send(
        user=user,
        title=title,
        body=body,
        url=url,
        icon=icon,
        subscriptions=subscriptions,
    )
    _log(user=user, channel=CHANNEL_PUSH, result=result, subject=title)
    return result


def send_sms(
    *,
    user=None,
    to_e164: Optional[str] = None,
    body: str,
) -> SendResult:
    """Send an SMS. Destination = ``to_e164`` or ``user.phone_e164``."""
    destination = (to_e164 or _resolve_phone(user) or "").strip()
    if not destination:
        result = SendResult(status="failed", error="No SMS destination")
        _log(user=user, channel=CHANNEL_SMS, result=result, subject=body[:80])
        return result

    result = sms_twilio.send(to_e164=destination, body=body)
    _log(user=user, channel=CHANNEL_SMS, result=result,
         subject=body[:80], target=destination)
    return result


# ---------------------------------------------------------------------------
# Generic dispatcher
# ---------------------------------------------------------------------------
def send(*, user, channel: str, **kwargs: Any) -> SendResult:
    """Generic dispatcher — channel must be ``email`` | ``push`` | ``sms``.

    Convenience for callers that want runtime channel selection (e.g.
    iterating per-user prefs). Keyword args are forwarded to the matching
    channel function.
    """
    if channel not in VALID_CHANNELS:
        return SendResult(status="failed", error=f"Unknown channel: {channel!r}")
    if channel == CHANNEL_EMAIL:
        return send_email(user=user, **kwargs)
    if channel == CHANNEL_PUSH:
        return send_push(user=user, **kwargs)
    return send_sms(user=user, **kwargs)


# ---------------------------------------------------------------------------
# Push subscription management
# ---------------------------------------------------------------------------
def subscribe_push(
    *,
    user,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: str = "",
) -> PushSubscription:
    """Idempotent upsert by ``endpoint``.

    A user re-subscribing from the same device updates the existing row
    rather than creating a duplicate; a user re-subscribing from a new
    device creates a new row.
    """
    sub, _ = PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            "user": user,
            "p256dh": p256dh,
            "auth": auth,
            "user_agent": (user_agent or "")[:255],
        },
    )
    return sub


def unsubscribe_push(*, user, endpoint: str) -> int:
    """Delete the subscription row(s) for (user, endpoint). Returns count."""
    deleted, _ = PushSubscription.objects.filter(
        user=user, endpoint=endpoint,
    ).delete()
    return deleted
