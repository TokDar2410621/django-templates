"""Base contract for newsletter_engine email backends.

A backend is anything with a ``send`` method matching the Protocol. Result
is a ``SendResult`` dataclass — identical in shape to the one in
``notifications_multichannel`` so callers can chain the two if they want.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol


@dataclass
class SendResult:
    """Outcome of one send attempt."""

    status: str  # "sent" | "skipped" | "failed"
    provider_message_id: str = ""
    error: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "sent"


class EmailBackend(Protocol):
    """Minimal contract every email backend implements.

    Backends should NEVER raise — every failure path returns a ``SendResult``
    with ``status='failed'`` so the campaign fan-out can mark Deliveries
    accordingly without try/except gymnastics at every call-site.
    """

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
    ) -> SendResult: ...  # pragma: no cover
