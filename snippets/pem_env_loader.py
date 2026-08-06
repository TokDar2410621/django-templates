"""Load PEM private keys from env — supporting both file paths and inline values.

PaaS platforms (Railway, Render, Heroku) treat env vars as single-line
strings. PEM blocks include real newlines, so users paste them with
literal ``\\n`` escape sequences. This helper un-escapes them at boot.

Two ways to provide a key are supported:

  1. Filesystem path (preferred for local dev where you've just
     downloaded the key from the provider):
         APPLE_PRIVATE_KEY_PATH=/path/to/AuthKey_ABC123.p8
     Relative paths are resolved against `BASE_DIR`.

  2. Inline value with ``\\n`` separators (for Railway etc. where you
     can't upload files):
         APPLE_PRIVATE_KEY=-----BEGIN PRIVATE KEY-----\\nMIGTAg...\\n-----END...

Returns "" when neither is set — caller can use degraded mode
(503 instead of 500) when the key is required for a feature.

USAGE — copy this file next to settings. Use it for:
  - Apple Sign-In .p8 private key
  - VAPID web-push private key
  - Any other PEM-encoded secret from a PaaS env var

Example in `base.py`:

    from .pem_loader import load_pem_from_env
    APPLE_PRIVATE_KEY = load_pem_from_env(
        path_key="APPLE_PRIVATE_KEY_PATH",
        inline_key="APPLE_PRIVATE_KEY",
        config=config,
        base_dir=BASE_DIR,
    )

    VAPID_PRIVATE_KEY = load_pem_from_env(
        path_key="VAPID_PRIVATE_KEY_PATH",
        inline_key="VAPID_PRIVATE_KEY",
        config=config,
        base_dir=BASE_DIR,
    )

`config` = python-decouple's `config` (or any equivalent).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


def load_pem_from_env(
    *,
    path_key: str,
    inline_key: str,
    config: Callable[..., Any],
    base_dir: Path | None = None,
) -> str:
    """Resolve a PEM-encoded value from either a file path or an inline env var.

    Returns "" if neither is set or the file can't be read.
    """
    raw_path = config(path_key, default="")
    if raw_path:
        p = Path(raw_path)
        if not p.is_absolute() and base_dir is not None:
            p = base_dir / p
        try:
            return p.read_text(encoding="utf-8")
        except OSError:
            return ""
    inline = config(inline_key, default="")
    return inline.replace("\\n", "\n") if inline else ""
