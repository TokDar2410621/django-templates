"""JWT authentication middleware for Channels WebSocket consumers.

Browsers cannot set custom headers on WebSocket, so the JWT access token
travels as a query parameter: ws://host/ws/messaging/<conv>/?token=<jwt>
Mount in config/asgi.py wrapping the WebSocket URLRouter. Same pattern as
the snippet channels_jwt_middleware.py; kept here so the app is autonomous.
"""
from __future__ import annotations

from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import AccessToken


@database_sync_to_async
def _get_user(token_str: str):
    User = get_user_model()
    try:
        user_id = AccessToken(token_str)["user_id"]
        return User.objects.get(pk=user_id, is_active=True)
    except (TokenError, InvalidToken, User.DoesNotExist, KeyError):
        return AnonymousUser()


class JWTAuthMiddleware(BaseMiddleware):
    """Populate ``scope['user']`` from the ?token= query parameter."""

    async def __call__(self, scope, receive, send):
        params = parse_qs(scope.get("query_string", b"").decode("utf-8"))
        tokens = params.get("token", [])
        scope["user"] = await _get_user(tokens[0]) if tokens else AnonymousUser()
        return await super().__call__(scope, receive, send)
