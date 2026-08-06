"""Abstract base for per-channel notification backends.

Every backend's ``send`` method must return a ``SendResult``. The service
layer never crashes a caller on provider errors — instead it inspects the
status and writes a ``NotificationLog`` row accordingly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class SendResult:
    """Outcome of a single send attempt across any channel."""

    # "sent" | "skipped" | "failed" — matches NotificationLog.STATUS_CHOICES
    status: str
    # Provider-side identifier (Resend message id, Twilio SID, push endpoint
    # hash, etc.) — empty when degraded / failed.
    provider_message_id: str = ""
    # Human-readable error explanation when status != "sent".
    error: str = ""
    # Free-form metadata that a caller might want to inspect (e.g. number
    # of push subscriptions reached). Not persisted.
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "sent"


class NotificationBackend(Protocol):
    """Minimal contract every channel backend implements.

    Kept as a ``Protocol`` rather than ABC so backends can stay tiny modules
    of free functions when there's nothing useful to instantiate (the
    Resend/pywebpush/Twilio APIs are global).
    """

    def send(self, **kwargs: Any) -> SendResult: ...  # pragma: no cover
