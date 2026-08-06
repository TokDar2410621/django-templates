"""Read-only queries for notifications."""
from __future__ import annotations

from typing import Iterable

from .models import PushSubscription


def active_push_subscriptions(user) -> Iterable[PushSubscription]:
    """All push subscriptions belonging to ``user`` (most recent first)."""
    return (
        PushSubscription.objects
        .filter(user=user)
        .order_by("-created_at")
    )


def has_any_channel(user) -> bool:
    """True if ``user`` is reachable through ANY channel.

    Useful for skipping a notification job entirely when the user has no
    email, no phone, and no push subscriptions.
    """
    if getattr(user, "email", None):
        return True
    if getattr(user, "phone_e164", None):
        return True
    return PushSubscription.objects.filter(user=user).exists()
