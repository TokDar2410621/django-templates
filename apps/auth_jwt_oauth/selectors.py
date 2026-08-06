"""Read-only queries for the auth app."""
from __future__ import annotations

from typing import Optional

from django.contrib.auth import get_user_model

from .models import UserProfile


def get_user_by_email(email: str):
    """Case-insensitive email lookup. Returns ``None`` when no match."""
    User = get_user_model()
    try:
        return User.objects.get(email__iexact=email.strip().lower())
    except User.DoesNotExist:
        return None


def email_exists(email: str) -> bool:
    return get_user_by_email(email) is not None


def get_profile(user) -> Optional[UserProfile]:
    """Fetch the profile row attached to a user. ``None`` when absent."""
    return UserProfile.objects.filter(user=user).first()


def is_banned(user) -> bool:
    """True when the user (or their profile) carries the banned flag.

    We honor either an ``is_banned`` field on the user model directly
    (kept for back-compat with project models that already had one) or
    on the attached ``UserProfile``.
    """
    if getattr(user, "is_banned", False):
        return True
    profile = get_profile(user)
    return bool(profile and profile.is_banned)
