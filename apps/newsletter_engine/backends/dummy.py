"""In-memory dummy backend — for tests and local development.

Records every send into ``DummyBackend.outbox`` (class-level list) so tests
can assert on what would have been sent. Use it by setting::

    NEWSLETTER_EMAIL_BACKEND = "newsletter_engine.backends.dummy.DummyBackend"
"""
from __future__ import annotations

import logging
from typing import Optional

from .base import EmailBackend, SendResult

logger = logging.getLogger(__name__)


class DummyBackend(EmailBackend):
    """Backend that drops everything into an in-process list."""

    # Class-level so tests can read it without instantiating the registered
    # singleton. Reset by calling DummyBackend.reset() at the top of a test.
    outbox: list[dict] = []

    @classmethod
    def reset(cls) -> None:
        cls.outbox = []

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
        entry = {
            "to": to,
            "subject": subject,
            "html": html,
            "text": text,
            "from_email": from_email,
            "reply_to": reply_to,
            "headers": dict(headers or {}),
        }
        type(self).outbox.append(entry)
        logger.debug("dummy.send to=%s subject=%s (#%d)", to, subject, len(type(self).outbox))
        return SendResult(
            status="sent",
            provider_message_id=f"dummy-{len(type(self).outbox)}",
        )
