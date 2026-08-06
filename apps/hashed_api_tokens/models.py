"""Hashed API token model — plain token shown ONCE, only SHA256 hash stored.

The plain token is generated in ``services.create_token`` and returned to the
caller exactly once. The database persists only:

* ``key_hash`` — SHA256(plain) hex digest, unique + indexed for O(1) lookup
* ``key_prefix`` — the first N chars of the plain token, kept ONLY for UI
  identification (``tkn_aB7c...``). Not enough on its own to reconstruct the
  full token.

Multiple tokens per user are supported — encourage one token per integration
so revoking n8n doesn't break Zapier.

Why no ``is_active`` boolean? Revocation is timestamped (``revoked_at``) so we
can audit *when* a token was disabled. ``is_active`` is a computed property.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


class ApiToken(models.Model):
    """One API token for one user.

    The plain-text token value is NEVER persisted — only its SHA256 hash. Format
    of the plain token: ``<prefix>_<43-char URL-safe random>`` where ``<prefix>``
    defaults to ``"tkn"`` and is configurable via the ``API_TOKEN_PREFIX``
    setting.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_tokens",
        help_text="Owner of this token. Cascade-deleted with the user.",
    )
    name = models.CharField(
        max_length=100,
        help_text=(
            "Friendly label set by the user. One token per integration is "
            "recommended. E.g. 'n8n production', 'Zapier', 'CI runner'."
        ),
    )

    # SHA256(plain_token).hexdigest() — 64 hex chars. The plain token is NEVER
    # stored, only this hash.
    key_hash = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="SHA256 of the plain token. Never reversible.",
    )
    # First chars of the plain token, kept for UI identification only.
    # E.g. ``tkn_aB7cD9eF`` is enough to recognize a token in a list, but not
    # enough to reconstruct the full 43-char random suffix.
    key_prefix = models.CharField(
        max_length=12,
        blank=True,
        default="",
        help_text="First chars of the plain token — for UI identification only.",
    )

    last_used_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Updated on each successful auth (rate-limited to avoid hammering the DB).",
    )
    revoked_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set when the user (or admin) revokes the token. NULL = active.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "hashed_api_token"
        ordering = ["-created_at"]
        indexes = [
            # Common query: "list all active tokens for user X" → covered.
            models.Index(fields=["user", "revoked_at"]),
        ]

    def __str__(self) -> str:
        owner = getattr(self.user, "username", None) or getattr(self.user, "email", str(self.user_id))
        return f"{owner}:{self.name} ({self.key_prefix}…)"

    @property
    def is_active(self) -> bool:
        """True when the token has not been revoked."""
        return self.revoked_at is None
