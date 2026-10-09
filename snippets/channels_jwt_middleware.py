"""Django Channels middleware: authenticate WebSocket connections via JWT.

WebSocket clients can't send custom HTTP headers from the browser, so the
JWT access token is passed as a query parameter:

    ws://host/ws/<path>/?token=<jwt>

This middleware decodes the token, looks up the user, and populates
``scope['user']`` for downstream consumers. Falls back to ``AnonymousUser``
on any error (invalid token, missing user, banned user).

USAGE: copy this file into your project (e.g. `apps/realtime/jwt_middleware.py`)
and wire it in `config/asgi.py`:

    from django.core.asgi import get_asgi_application
    from channels.routing import ProtocolTypeRouter, URLRouter
    from channels.auth import AuthMiddlewareStack
    from .jwt_middleware import JWTAuthMiddleware
    from . import routing

    application = ProtocolTypeRouter({
        "http": get_asgi_application(),
        "websocket": JWTAuthMiddleware(
            URLRouter(routing.websocket_urlpatterns)
        ),
    })

You can stack it with AuthMiddlewareStack if you want both cookie-session
and JWT auth supported on the same WS endpoint:

    "websocket": AuthMiddlewareStack(JWTAuthMiddleware(URLRouter(...)))

Without ``?token=``, the user already set by AuthMiddlewareStack is kept.
(Before 2026-10-09 it was overwritten with AnonymousUser, which logged out
every session-authenticated client of a stacked setup.)

EXTRA-FILTERS: by default this middleware filters out banned users via
a ``is_banned=False`` lookup. If your User model doesn't have that field,
remove the filter (see `_get_user` below).

DEPENDS ON: `channels>=4.0`, `djangorestframework-simplejwt>=5.3`.
"""
from __future__ import annotations

from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import AccessToken

User = get_user_model()


@database_sync_to_async
def _get_user(token_str: str):
    """Validate a JWT and return the matching active user, or AnonymousUser."""
    try:
        validated = AccessToken(token_str)
        user_id = validated["user_id"]
        # Drop the `is_banned=False` filter if your User model lacks that field.
        lookup = {"pk": user_id, "is_active": True}
        if _user_has_field("is_banned"):
            lookup["is_banned"] = False
        return User.objects.get(**lookup)
    except (TokenError, InvalidToken, User.DoesNotExist, KeyError):
        return AnonymousUser()


def _user_has_field(field_name: str) -> bool:
    return any(f.name == field_name for f in User._meta.get_fields())


class JWTAuthMiddleware(BaseMiddleware):
    """Populate ``scope['user']`` from the ``?token=`` query parameter."""

    async def __call__(self, scope, receive, send):
        query_string = scope.get("query_string", b"").decode("utf-8")
        params = parse_qs(query_string)
        token_list = params.get("token", [])
        if token_list:
            scope["user"] = await _get_user(token_list[0])
        elif "user" not in scope:
            # Keep a user already set by AuthMiddlewareStack (cookie session).
            scope["user"] = AnonymousUser()
        return await super().__call__(scope, receive, send)
