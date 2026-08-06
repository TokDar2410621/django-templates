"""Pluggable email backends for newsletter_engine.

The backend is resolved at call-time from the ``NEWSLETTER_EMAIL_BACKEND``
setting (dotted path). Default = ``newsletter_engine.backends.resend.ResendBackend``.

If your project also uses the ``notifications_multichannel`` template, you
can wire its ``send_email`` into here by writing a small adapter — that
way both transactional + marketing email go through one channel and share
the same Gmail filter rules / Reply-To routing.
"""
from __future__ import annotations

import logging
from importlib import import_module
from typing import Optional

from django.conf import settings

from .base import EmailBackend, SendResult

logger = logging.getLogger(__name__)


_DEFAULT_BACKEND_PATH = "newsletter_engine.backends.resend.ResendBackend"

_cached_backend: Optional[EmailBackend] = None


def get_email_backend(*, refresh: bool = False) -> EmailBackend:
    """Return the configured email backend (cached).

    Pass ``refresh=True`` to force re-import — useful in tests that override
    ``NEWSLETTER_EMAIL_BACKEND`` after import-time.
    """
    global _cached_backend
    if _cached_backend is not None and not refresh:
        return _cached_backend

    dotted = getattr(settings, "NEWSLETTER_EMAIL_BACKEND", _DEFAULT_BACKEND_PATH)
    module_path, _, class_name = dotted.rpartition(".")
    if not module_path:
        raise ImportError(f"NEWSLETTER_EMAIL_BACKEND must be a dotted path, got {dotted!r}")
    module = import_module(module_path)
    cls = getattr(module, class_name)
    backend = cls()
    _cached_backend = backend
    logger.debug("newsletter.backend resolved %s", dotted)
    return backend


__all__ = ["EmailBackend", "SendResult", "get_email_backend"]
