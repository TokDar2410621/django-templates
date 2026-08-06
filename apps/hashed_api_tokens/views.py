"""Token management endpoints (list, create, revoke).

These views use whatever auth backend the project already has wired (JWT,
session, …) — they manage the user's tokens, they do NOT authenticate VIA
tokens. The actual token-authenticated endpoints live in the project's own
``api/v1/*`` views and declare ``authentication_classes=[HashedTokenAuthentication]``.

Endpoints (mount on ``/api/tokens/``):

* ``GET  /api/tokens/`` — list the requester's active tokens
* ``POST /api/tokens/`` — create a new token, returns the plain value ONCE
* ``POST /api/tokens/<id>/revoke/`` — revoke (soft-delete) a token
"""
from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .selectors import list_user_tokens
from .serializers import (
    ApiTokenSerializer,
    CreateTokenRequestSerializer,
    CreateTokenResponseSerializer,
)
from .services import create_token, revoke_token

logger = logging.getLogger(__name__)


_SHOWN_ONCE_MESSAGE = (
    "Store this token somewhere safe — it will never be displayed again."
)


class TokenListCreateView(APIView):
    """``GET`` lists the requester's tokens; ``POST`` creates a new one.

    POST response is the ONLY place the plain token appears. The frontend
    should display it once, encourage copy-to-clipboard, and then hide it.
    """
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        include_revoked = request.query_params.get("include_revoked") in {
            "1", "true", "True", "yes",
        }
        tokens = list_user_tokens(request.user, include_revoked=include_revoked)
        return Response({"results": ApiTokenSerializer(tokens, many=True).data})

    def post(self, request: Request) -> Response:
        ser = CreateTokenRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        token, plain = create_token(request.user, ser.validated_data["name"])

        payload = CreateTokenResponseSerializer(token).data
        payload["token"] = plain  # injected — see serializer docstring
        payload["message"] = _SHOWN_ONCE_MESSAGE
        return Response(payload, status=status.HTTP_201_CREATED)


class TokenRevokeView(APIView):
    """``POST /api/tokens/<id>/revoke/`` — soft-revoke a token.

    Idempotent: revoking an already-revoked token returns 200 with the same
    payload, not 404.
    """
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk: int) -> Response:
        token = revoke_token(pk, request.user)
        if token is None:
            return Response(
                {"detail": "Token not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(ApiTokenSerializer(token).data)
