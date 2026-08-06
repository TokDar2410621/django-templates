"""DRF custom exception handler — turn Ratelimited into HTTP 429.

`django_ratelimit.exceptions.Ratelimited` subclasses `PermissionDenied`,
which DRF's default handler maps to HTTP 403. That's misleading — the
client wasn't forbidden, they hit a rate limit and should retry later.

This handler intercepts `Ratelimited` first and returns HTTP 429 with a
clear message, then delegates everything else to DRF's default.

USAGE — copy this file into your project (e.g. `apps/users/exceptions.py`),
then in `settings.py`:

    REST_FRAMEWORK = {
        # ...
        "EXCEPTION_HANDLER": "<your_module_path>.custom_exception_handler",
    }

DEPENDS ON — `django-ratelimit>=4.0`, `djangorestframework>=3.14`.

LOCALIZATION — the error message is in English by default. Override by
passing a custom `message` (see `make_handler`) or by editing the string
inline.
"""
from __future__ import annotations

from typing import Callable

from django_ratelimit.exceptions import Ratelimited
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_default_handler


_DEFAULT_MESSAGE = "Too many requests. Please try again later."


def custom_exception_handler(exc, context):
    """Drop-in DRF EXCEPTION_HANDLER replacement."""
    if isinstance(exc, Ratelimited):
        return Response({"detail": _DEFAULT_MESSAGE}, status=429)
    return drf_default_handler(exc, context)


def make_handler(message: str) -> Callable:
    """Factory if you want a custom message (e.g. localized)."""
    def handler(exc, context):
        if isinstance(exc, Ratelimited):
            return Response({"detail": message}, status=429)
        return drf_default_handler(exc, context)
    return handler
