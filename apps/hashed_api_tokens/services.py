"""Token services — create, revoke, hash, generate.

The ONLY place that produces a plain-text token is ``create_token``. Every
other code path operates on the hash. This keeps the attack surface tiny:
if someone dumps the DB, no token survives.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from typing import Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import ApiToken

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configurable prefix
# ---------------------------------------------------------------------------

DEFAULT_TOKEN_PREFIX = "tkn"
# How many chars of the plain token to persist as ``key_prefix`` (for UI
# display). With the default ``tkn_`` prefix this gives "tkn_aB7cD9eF" (12
# chars) — recognizable in a list but useless without the rest.
_KEY_PREFIX_LEN = 12
# Random suffix length in URL-safe characters (NOT bytes). 32 bytes of entropy
# → ~43 URL-safe chars after base64-without-padding.
_RANDOM_BYTES = 32


def get_token_prefix() -> str:
    """Return the configured plain-token prefix. Defaults to ``"tkn"``."""
    return getattr(settings, "API_TOKEN_PREFIX", DEFAULT_TOKEN_PREFIX)


# ---------------------------------------------------------------------------
# Hashing — internal helper. We use SHA256 because:
#   - the plain token is already 32 bytes of cryptographic randomness, so
#     a slow hash (bcrypt/argon2) buys nothing — there's no useful pre-image
#     attack surface against high-entropy input
#   - SHA256 is fast (lookup latency matters per-request)
#   - it's deterministic, so we can index ``key_hash`` for O(1) lookup
# Do NOT switch to bcrypt here — it would force a scan of every row on each
# auth request, which is catastrophic at any reasonable scale.
# ---------------------------------------------------------------------------

def hash_token(plain: str) -> str:
    """Return the SHA256 hex digest of ``plain``. Same function used by
    ``create_token`` (on write) and ``HashedTokenAuthentication`` (on read).
    """
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def generate_plain_token() -> tuple[str, str, str]:
    """Produce a new (plain_token, key_hash, key_prefix) triple.

    Returns:
        plain: the full token to return to the user ONCE
        key_hash: what we persist to ``ApiToken.key_hash``
        key_prefix: what we persist to ``ApiToken.key_prefix`` (UI label)
    """
    plain = f"{get_token_prefix()}_{secrets.token_urlsafe(_RANDOM_BYTES)}"
    return plain, hash_token(plain), plain[:_KEY_PREFIX_LEN]


# ---------------------------------------------------------------------------
# Public services
# ---------------------------------------------------------------------------

@transaction.atomic
def create_token(user, name: str) -> tuple[ApiToken, str]:
    """Create a new ApiToken for ``user`` with friendly label ``name``.

    Returns ``(token_obj, plain_token)``. The plain token MUST be shown to
    the user immediately and never again — it is not recoverable from the DB.

    Raises ``ValueError`` if ``name`` is empty after stripping.
    """
    label = (name or "").strip()
    if not label:
        raise ValueError("name is required and must be non-empty after stripping.")
    label = label[:100]

    plain, key_hash, key_prefix = generate_plain_token()
    token = ApiToken.objects.create(
        user=user,
        name=label,
        key_hash=key_hash,
        key_prefix=key_prefix,
    )
    logger.info(
        "hashed_api_tokens.created token_id=%s user_id=%s prefix=%s",
        token.pk, getattr(user, "pk", None), key_prefix,
    )
    return token, plain


def revoke_token(token_id: int, by_user) -> Optional[ApiToken]:
    """Soft-revoke a token by id. Only the owner OR a staff user may revoke.

    Returns the updated ``ApiToken`` row, or ``None`` if not found / not
    authorized. Idempotent — calling on an already-revoked token is a no-op
    and still returns the row (so callers can show "already revoked" instead
    of "not found").
    """
    qs = ApiToken.objects.filter(pk=token_id)
    if not getattr(by_user, "is_staff", False):
        qs = qs.filter(user=by_user)
    token = qs.first()
    if token is None:
        return None
    if token.revoked_at is not None:
        return token  # idempotent
    token.revoked_at = timezone.now()
    token.save(update_fields=["revoked_at"])
    logger.info(
        "hashed_api_tokens.revoked token_id=%s by_user_id=%s",
        token.pk, getattr(by_user, "pk", None),
    )
    return token


def find_by_plain(plain: str) -> Optional[ApiToken]:
    """Lookup utility — primarily for tests and debug scripts.

    Production code should use ``HashedTokenAuthentication`` (which already
    filters out revoked tokens and updates ``last_used_at``).
    """
    if not plain:
        return None
    try:
        return ApiToken.objects.select_related("user").get(key_hash=hash_token(plain))
    except ApiToken.DoesNotExist:
        return None
