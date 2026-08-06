"""Read-only queries for ApiToken."""
from __future__ import annotations

from typing import Optional

from django.db.models import QuerySet

from .models import ApiToken


def list_user_tokens(user, *, include_revoked: bool = False) -> QuerySet[ApiToken]:
    """All tokens owned by ``user``.

    By default only active (non-revoked) tokens are returned — that's what
    99% of UI screens need ("manage your active tokens"). Pass
    ``include_revoked=True`` for audit / history views.
    """
    qs = ApiToken.objects.filter(user=user)
    if not include_revoked:
        qs = qs.filter(revoked_at__isnull=True)
    return qs.order_by("-created_at")


def find_by_hash(key_hash: str) -> Optional[ApiToken]:
    """O(1) lookup by ``key_hash`` (unique index). Returns active OR revoked
    token; the caller decides whether to honor a revoked one.
    """
    if not key_hash:
        return None
    try:
        return ApiToken.objects.select_related("user").get(key_hash=key_hash)
    except ApiToken.DoesNotExist:
        return None
