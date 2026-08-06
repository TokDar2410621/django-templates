"""Public read API for legal documents.

Both endpoints are AllowAny + authentication_classes=() — a fresh visitor
must be able to read the ToS before clicking "accept" on the signup form.
"""
from __future__ import annotations

from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import _default_language, _languages
from .selectors import list_active_for_language
from .serializers import LegalDocumentDetailSerializer, LegalDocumentIndexSerializer
from .services import get_active


def _allowed_language_codes() -> set[str]:
    return {code for code, _ in _languages()}


def pick_language(request: Request) -> str:
    """Resolve the language for this request.

    Priority:
      1. ``?lang=`` query parameter
      2. ``Accept-Language`` header
      3. ``LEGAL_DEFAULT_LANGUAGE`` setting fallback
    """
    allowed = _allowed_language_codes()
    q = (request.GET.get("lang") or "").strip().lower()
    if q in allowed:
        return q
    accept = (request.META.get("HTTP_ACCEPT_LANGUAGE") or "").lower()
    for token in accept.replace(";", ",").split(","):
        prefix = token.strip()[:2]
        if prefix in allowed:
            return prefix
    return _default_language()


class LegalIndexView(APIView):
    """GET /api/legal/?lang=fr — list all kinds with their active versions."""
    permission_classes = (AllowAny,)
    authentication_classes = ()

    def get(self, request: Request) -> Response:
        language = pick_language(request)
        active = list_active_for_language(language)
        return Response(
            LegalDocumentIndexSerializer(active, many=True).data,
        )


class LegalDetailView(APIView):
    """GET /api/legal/<kind>/?lang=fr — full active version of one document."""
    permission_classes = (AllowAny,)
    authentication_classes = ()

    def get(self, request: Request, kind: str) -> Response:
        language = pick_language(request)
        doc = get_active(kind, language)
        if doc is None:
            return Response(
                {"detail": "Legal document not published."}, status=404,
            )
        return Response(LegalDocumentDetailSerializer(doc).data)
