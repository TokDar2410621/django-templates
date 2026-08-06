"""DRF custom exception handler.

Wire this into DRF settings::

    REST_FRAMEWORK = {
        # ...
        "EXCEPTION_HANDLER":
            "auth_jwt_oauth.exceptions.custom_exception_handler",
    }

Why: ``django_ratelimit.exceptions.Ratelimited`` subclasses
``PermissionDenied`` so DRF's default handler maps it to **403**. That
hides rate-limit hits behind the same status code as auth failures and
makes the SPA show the wrong error UI. We force it to **429** with a
clear French message.

The handler is a no-op when ``django-ratelimit`` is not installed — the
``ImportError`` is caught at module import time.
"""
from __future__ import annotations

from typing import Any

from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_default_handler

try:
    from django_ratelimit.exceptions import Ratelimited  # type: ignore
except ImportError:  # pragma: no cover — optional dependency
    Ratelimited = None  # type: ignore[assignment]


_DEFAULT_429_MESSAGE = "Tu as envoyé trop de requêtes. Réessaie plus tard."


def custom_exception_handler(exc: BaseException, context: Any) -> Response | None:
    if Ratelimited is not None and isinstance(exc, Ratelimited):
        return Response({"detail": _DEFAULT_429_MESSAGE}, status=429)
    return drf_default_handler(exc, context)
