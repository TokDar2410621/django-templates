"""Custom exceptions for the billing/quota subsystem.

We raise ``QuotaExceeded`` (NOT DRF's ``PermissionDenied``) from the service
layer so callers in non-DRF contexts (Celery tasks, management commands,
WebSocket consumers) can react without importing DRF. The DRF view layer
catches it and returns a 402 Payment Required.
"""
from __future__ import annotations

from typing import Optional


class QuotaExceeded(Exception):
    """Raised when a user's plan quota AND credit balance are both exhausted.

    Attributes
    ----------
    resource_key : str
        The resource that triggered the exception (e.g. ``"article_generation"``).
    plan_limit : Optional[int]
        Plan-level monthly limit (``None`` = unlimited; in practice this is
        never raised when ``plan_limit is None``).
    current_count : int
        Usage counter at the time of the call (i.e. articles already consumed
        this month).
    credits_available : int
        Top-up credit balance at the time of the call (zero when the user has
        no credits left either).
    requested : int
        Number of units the caller asked to consume.
    """

    def __init__(
        self,
        *,
        resource_key: str,
        plan_limit: Optional[int],
        current_count: int,
        credits_available: int = 0,
        requested: int = 1,
        message: Optional[str] = None,
    ) -> None:
        self.resource_key = resource_key
        self.plan_limit = plan_limit
        self.current_count = current_count
        self.credits_available = credits_available
        self.requested = requested
        if message is None:
            message = (
                f"Quota exhausted for resource '{resource_key}': "
                f"used {current_count}/{plan_limit}, "
                f"credits available={credits_available}, requested={requested}."
            )
        super().__init__(message)


class InvalidPlan(Exception):
    """Raised when a plan slug isn't in ``SAAS_PLAN_CHOICES``."""
