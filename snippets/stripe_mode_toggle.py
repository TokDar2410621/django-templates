"""Toggle Stripe keys between test/live mode via a single env var.

In dev you want test keys; in prod you want live keys. Flipping a single
`STRIPE_MODE=test|live` env var should resolve all three pieces (secret
key, webhook secret, Connect client id) without editing the codebase.

Each key is resolved by first looking for `<base>_<MODE>` (e.g.
`STRIPE_SECRET_KEY_TEST`), then falling back to `<base>` (so old setups
without the suffix keep working — back-compat shim).

USAGE — copy this whole file into a `stripe_env.py` next to your settings,
then in `base.py`:

    from .stripe_env import build_stripe_env
    STRIPE = build_stripe_env(config=config)

    # Then access:
    STRIPE_MODE = STRIPE["mode"]
    STRIPE_SECRET_KEY = STRIPE["secret_key"]
    STRIPE_WEBHOOK_SECRET = STRIPE["webhook_secret"]
    STRIPE_CONNECT_CLIENT_ID = STRIPE["connect_client_id"]

`config` = python-decouple's `config` (or any equivalent).

ENV VARS — set whichever pair you need (TEST in dev, LIVE in prod):
    STRIPE_MODE=test
    STRIPE_SECRET_KEY_TEST=sk_test_...
    STRIPE_WEBHOOK_SECRET_TEST=whsec_...
    STRIPE_CONNECT_CLIENT_ID_TEST=ca_...

    STRIPE_MODE=live
    STRIPE_SECRET_KEY_LIVE=sk_live_...
    STRIPE_WEBHOOK_SECRET_LIVE=whsec_...
    STRIPE_CONNECT_CLIENT_ID_LIVE=ca_...
"""
from __future__ import annotations

from typing import Any, Callable


_DEFAULT_BASES = (
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "STRIPE_CONNECT_CLIENT_ID",
)


def stripe_env_for(
    base: str,
    *,
    mode: str,
    config: Callable[..., Any],
) -> str:
    """Resolve a single Stripe env var with mode-suffix preference.

    Looks for `<base>_<MODE>` first, then `<base>` (back-compat), then "".
    """
    suffixed = config(f"{base}_{mode.upper()}", default="")
    return suffixed or config(base, default="")


def build_stripe_env(
    *,
    config: Callable[..., Any],
    bases: tuple[str, ...] = _DEFAULT_BASES,
) -> dict[str, str]:
    """Return a dict of resolved Stripe env vars + the chosen mode.

    Mode comes from `STRIPE_MODE` env var (lowercased, defaults to `test`).
    """
    mode = config("STRIPE_MODE", default="test").lower()
    result: dict[str, str] = {"mode": mode}
    for base in bases:
        # Convert STRIPE_SECRET_KEY → secret_key
        key = base.removeprefix("STRIPE_").lower()
        result[key] = stripe_env_for(base, mode=mode, config=config)
    return result
