"""DRF authentication backend — ``Authorization: Bearer <token>`` or ``X-Api-Key``.

Plugs into ``DEFAULT_AUTHENTICATION_CLASSES`` (or per-view ``authentication_classes``).
On success, ``request.user`` is the token's owner and ``request.auth`` is the
``ApiToken`` instance (so views can inspect ``request.auth.name`` for audit
logs, etc.).

Why two headers? ``Authorization: Bearer`` is the canonical REST convention,
but plenty of webhook senders + integration platforms (n8n, Zapier, vendor
admin panels) only let you set an arbitrary header — ``X-Api-Key`` covers that.
``Authorization`` takes priority when both are present.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone
from rest_framework import authentication, exceptions

from .models import ApiToken
from .services import get_token_prefix, hash_token

logger = logging.getLogger(__name__)


# Throttle the ``last_used_at`` write so a high-QPS integration doesn't
# generate one UPDATE per request. One minute is short enough to be useful
# ("when did this token last call us?") and long enough to keep write load
# trivial.
_LAST_USED_UPDATE_WINDOW = timedelta(minutes=1)


class HashedTokenAuthentication(authentication.BaseAuthentication):
    """Authenticate against the ``ApiToken`` table via SHA256 hash lookup.

    Accepted formats (first non-empty wins):

    * ``Authorization: Bearer <plain_token>``
    * ``X-Api-Key: <plain_token>``

    Returns ``(user, token_obj)`` on success. Raises ``AuthenticationFailed``
    on any explicit auth attempt that doesn't match a non-revoked token.
    Returns ``None`` when no auth header is present at all — that lets other
    auth backends (JWT, session, …) try.
    """

    keyword = "Bearer"
    header_x_api_key = "HTTP_X_API_KEY"

    def authenticate(self, request):
        plain = self._extract_token(request)
        if plain is None:
            return None  # no header → let other auth backends try

        # Soft format check. We don't enforce the prefix strictly — if a user
        # mis-pastes a token without the prefix the SHA lookup will simply
        # fail and we return AuthenticationFailed. But if the prefix IS
        # configured and the token has a different obvious-prefix shape,
        # we reject early with a clearer error.
        prefix = get_token_prefix()
        if "_" in plain and not plain.startswith(f"{prefix}_"):
            # User clearly pasted SOMETHING_else_format → not ours.
            raise exceptions.AuthenticationFailed("Invalid token format.")

        try:
            token = ApiToken.objects.select_related("user").get(
                key_hash=hash_token(plain),
                revoked_at__isnull=True,
            )
        except ApiToken.DoesNotExist:
            # Same error for "unknown token" and "revoked token" — don't leak
            # which one to a probing attacker.
            raise exceptions.AuthenticationFailed("Invalid or revoked token.")

        self._touch_last_used(token)
        return (token.user, token)

    def authenticate_header(self, request):
        return self.keyword

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _extract_token(self, request) -> str | None:
        """Return the plain token string from headers, or None."""
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if auth_header.startswith(self.keyword + " "):
            plain = auth_header.split(" ", 1)[1].strip()
            if plain:
                return plain
        api_key = request.META.get(self.header_x_api_key, "").strip()
        if api_key:
            return api_key
        return None

    def _touch_last_used(self, token: ApiToken) -> None:
        """Rate-limited update of ``last_used_at`` to avoid one write/request.

        Uses ``.update()`` rather than ``.save()`` so we skip ``auto_now`` /
        signals and incur exactly one SQL UPDATE.
        """
        now = timezone.now()
        if token.last_used_at and (now - token.last_used_at) < _LAST_USED_UPDATE_WINDOW:
            return
        try:
            ApiToken.objects.filter(pk=token.pk).update(last_used_at=now)
        except Exception:  # pragma: no cover — defensive; never block the request
            logger.warning("hashed_api_tokens.last_used_update_failed token_id=%s", token.pk)
