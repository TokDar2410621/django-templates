"""Settings helpers — import into your project's ``settings.py``.

The ``_stripe_env`` helper is the same toggle pattern used by SendMeNow:
a single ``STRIPE_MODE=test|live`` env var flips the whole triplet
(secret / webhook / connect client id) without renaming the vars
Railway / your hosting already has.

Usage in your ``settings.py``::

    from stripe_connect_multivendor.settings_helpers import _stripe_env

    STRIPE_MODE = os.environ.get("STRIPE_MODE", "live").lower()
    STRIPE_SECRET_KEY = _stripe_env("STRIPE_SECRET_KEY", STRIPE_MODE)
    STRIPE_WEBHOOK_SECRET = _stripe_env("STRIPE_WEBHOOK_SECRET", STRIPE_MODE)
    STRIPE_CONNECT_CLIENT_ID = _stripe_env("STRIPE_CONNECT_CLIENT_ID", STRIPE_MODE)

Resolution order for ``_stripe_env("STRIPE_SECRET_KEY", "test")``:
    1. ``STRIPE_SECRET_KEY_TEST``     (mode-specific — preferred)
    2. ``STRIPE_SECRET_KEY``          (back-compat single-mode)
    3. ``""``                         (empty — caller branches on truthiness)
"""
from __future__ import annotations

import os
from typing import Optional


def _stripe_env(base: str, mode: Optional[str] = None) -> str:
    """Resolve a Stripe env var honouring the optional mode suffix.

    ``mode`` defaults to ``$STRIPE_MODE`` (lowercased; falls back to
    ``"live"`` if unset). Pass an explicit mode to override (e.g. in
    tests or feature flags).
    """
    if mode is None:
        mode = os.environ.get("STRIPE_MODE", "live").lower()
    suffixed = os.environ.get(f"{base}_{mode.upper()}", "")
    return suffixed or os.environ.get(base, "")


def stripe_default_currency() -> str:
    """Return the configured default currency (uppercase ISO 4217).

    Defaults to ``CAD`` if ``STRIPE_DEFAULT_CURRENCY`` is unset. Override
    per-payout by passing ``currency=`` to ``create_payout``.
    """
    return os.environ.get("STRIPE_DEFAULT_CURRENCY", "CAD").upper()
