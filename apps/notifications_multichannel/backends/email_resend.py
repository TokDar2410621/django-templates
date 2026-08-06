"""Email backend — Resend HTTP API.

Why Resend (vs Django's SMTP backend)?
  - Modern transactional API with a single HTTP call (no SMTP holds, no
    long-running TLS handshakes on Railway/serverless).
  - Domain reputation handled by them.
  - Maps cleanly to role-based senders (``noreply``, ``notification``,
    ``orders``) — each address gets its own filter rules in Gmail and its
    own ``Reply-To`` routing.

Degraded mode: when ``RESEND_API_KEY`` is empty, log + return
``status='skipped'``. Callers never need to check creds themselves.
"""
from __future__ import annotations

import logging
from typing import Optional

import requests
from django.conf import settings

from .base import SendResult

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"
_DEFAULT_TIMEOUT = 10  # seconds


def _resolve_sender(role: str) -> Optional[str]:
    """Pick the from-address for ``role``.

    Priority:
      1. ``settings.RESEND_SENDERS[role]``
      2. ``settings.RESEND_FROM_EMAIL`` (single fallback for all roles)
    """
    senders: dict = getattr(settings, "RESEND_SENDERS", {}) or {}
    sender = senders.get(role) or getattr(settings, "RESEND_FROM_EMAIL", "")
    return sender or None


def _resolve_reply_to(role: str, override: Optional[str]) -> Optional[str]:
    if override:
        return override
    reply_to_map: dict = getattr(settings, "RESEND_REPLY_TO", {}) or {}
    return reply_to_map.get(role) or None


def send(
    *,
    role: str,
    to: str,
    subject: str,
    html: str,
    text: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> SendResult:
    """Send a transactional email via Resend.

    Returns a SendResult — never raises.
    """
    api_key = getattr(settings, "RESEND_API_KEY", "")
    if not api_key:
        logger.info(
            "notifications.email skipped (no RESEND_API_KEY) — to=%s subject=%s",
            to, subject,
        )
        return SendResult(status="skipped", error="RESEND_API_KEY not configured")

    sender = _resolve_sender(role)
    if not sender:
        logger.warning(
            "notifications.email skipped — no sender configured for role=%s",
            role,
        )
        return SendResult(
            status="skipped",
            error=f"No sender configured for role={role!r}",
        )

    if not to:
        return SendResult(status="failed", error="Missing 'to' address")

    payload: dict = {
        "from": sender,
        "to": [to],
        "subject": subject,
        "html": html,
    }
    if text:
        payload["text"] = text

    resolved_reply_to = _resolve_reply_to(role, reply_to)
    if resolved_reply_to:
        payload["reply_to"] = [resolved_reply_to]

    try:
        resp = requests.post(
            RESEND_API_URL,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=_DEFAULT_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.warning("notifications.email transport error: %s", exc)
        return SendResult(status="failed", error=f"Transport error: {exc}")

    if resp.status_code >= 400:
        snippet = resp.text[:200] if resp.text else ""
        logger.warning(
            "notifications.email failed status=%s body=%s",
            resp.status_code, snippet,
        )
        return SendResult(
            status="failed",
            error=f"HTTP {resp.status_code}: {snippet}",
        )

    try:
        body = resp.json() or {}
    except ValueError:
        body = {}
    return SendResult(
        status="sent",
        provider_message_id=str(body.get("id") or ""),
    )
