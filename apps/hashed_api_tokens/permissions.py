"""DRF permission classes for hashed-api-tokens."""
from __future__ import annotations

from rest_framework import permissions

from .models import ApiToken


class HasActiveApiToken(permissions.BasePermission):
    """Allow access only when the request was authenticated by an
    ``ApiToken`` that is NOT revoked.

    Use this in addition to ``HashedTokenAuthentication`` when you want to
    block requests that authenticated by some OTHER method (session, JWT)
    from hitting machine-only endpoints.
    """

    message = "An active API token is required for this endpoint."

    def has_permission(self, request, view) -> bool:
        auth = getattr(request, "auth", None)
        if not isinstance(auth, ApiToken):
            return False
        return auth.revoked_at is None
