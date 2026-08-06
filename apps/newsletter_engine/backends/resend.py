"""Resend HTTP backend.

Direct ``requests`` against ``https://api.resend.com/emails`` — no SDK
dependency, matches the pattern of ``notifications_multichannel``.

Degraded mode: when ``NEWSLETTER_RESEND_API_KEY`` (preferred) or
``RESEND_API_KEY`` is empty, returns ``status='skipped'`` so the
campaign fan-out doesn't error out — it just records 0 sends.
"""
from __future__ import annotations

import logging
from typing import Optional

import requests
from django.conf import settings

from .base import EmailBackend, SendResult

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"
_DEFAULT_TIMEOUT = 10  # seconds


def _api_key() -> str:
    return (
        getattr(settings, "NEWSLETTER_RESEND_API_KEY", "")
        or getattr(settings, "RESEND_API_KEY", "")
    )


class ResendBackend(EmailBackend):
    """Default newsletter_engine email backend."""

    def send(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        text: str = "",
        from_email: str,
        reply_to: str = "",
        headers: Optional[dict[str, str]] = None,
    ) -> SendResult:
        api_key = _api_key()
        if not api_key:
            logger.info(
                "newsletter.resend skipped (no API key) to=%s subject=%s",
                to, subject,
            )
            return SendResult(status="skipped", error="Resend API key not configured")
        if not to:
            return SendResult(status="failed", error="Missing 'to'")
        if not from_email:
            return SendResult(status="failed", error="Missing 'from_email'")

        payload: dict = {
            "from": from_email,
            "to": [to],
            "subject": subject,
            "html": html,
        }
        if text:
            payload["text"] = text
        if reply_to:
            payload["reply_to"] = [reply_to]
        if headers:
            payload["headers"] = headers

        try:
            resp = requests.post(
                RESEND_API_URL,
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=_DEFAULT_TIMEOUT,
            )
        except requests.RequestException as exc:
            logger.warning("newsletter.resend transport error: %s", exc)
            return SendResult(status="failed", error=f"Transport error: {exc}")

        if resp.status_code >= 400:
            snippet = (resp.text or "")[:200]
            logger.warning(
                "newsletter.resend rejected status=%s body=%s",
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
