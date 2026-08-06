"""HTTP API for conversational_ai_engine.

Endpoints
---------

* ``POST /generate/``         — one-shot generation, returns JSON.
* ``POST /generate/stream/``  — server-sent events stream.
* ``GET/PUT /persona/``       — read/update the caller's persona.
* CRUD ``/templates/``        — manage user prompt templates.
* ``GET /generations/``       — list the caller's recent generations.

The views intentionally accept *both* JSON and multipart so the frontend
can upload images directly. When multipart is used, the ``images`` form
field becomes the ``vision_images`` payload.

Anonymous trial
---------------

When the caller is not authenticated, the engine falls back to the Django
session key. Rate limiting is left to the project (use DRF throttling or
a middleware — the engine just records the session key on every row).
"""
from __future__ import annotations

import base64
import logging

from django.http import StreamingHttpResponse
from rest_framework import status, viewsets
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Generation, PersonaContext, PromptTemplate
from .providers.base import (
    ProviderAuth,
    ProviderError,
    ProviderRateLimit,
    ProviderUnavailable,
)
from .selectors import (
    get_persona,
    list_user_templates,
    recent_generations,
    recent_generations_for_session,
)
from .serializers import (
    GenerateRequestSerializer,
    GenerationSerializer,
    PersonaContextSerializer,
    PromptTemplateSerializer,
)
from .services import generate

logger = logging.getLogger(__name__)

MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_IMAGES = 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _resolve_session_key(request: Request) -> str:
    """Anonymous trial — ensure a session key exists and return it.

    Django creates the session lazily; we touch it so subsequent calls in
    the same browser keep producing the same key.
    """
    if not request.session.session_key:
        request.session.save()
    return request.session.session_key or ""


def _extract_vision_images(request: Request) -> list[dict]:
    """Pull vision payloads from either JSON body or multipart upload."""
    images: list[dict] = []

    # Multipart path (`images` form field) — encode in-memory to base64.
    for upload in request.FILES.getlist("images")[:MAX_IMAGES]:
        if upload.size > MAX_IMAGE_SIZE:
            raise ValueError(
                f"Image too large ({upload.size // (1024 * 1024)}MB). "
                f"Max {MAX_IMAGE_SIZE // (1024 * 1024)}MB."
            )
        media_type = getattr(upload, "content_type", "image/png")
        if media_type not in ALLOWED_IMAGE_TYPES:
            raise ValueError(f"Unsupported image type: {media_type}")
        images.append({
            "data": base64.standard_b64encode(upload.read()).decode("ascii"),
            "media_type": media_type,
        })

    # JSON path (`vision_images: [{data_base64, media_type}]`).
    for img in (request.data.get("vision_images") or [])[:MAX_IMAGES]:
        media_type = img.get("media_type", "image/png")
        if media_type not in ALLOWED_IMAGE_TYPES:
            raise ValueError(f"Unsupported image type: {media_type}")
        images.append({
            "data": img.get("data_base64", ""),
            "media_type": media_type,
        })

    return images[:MAX_IMAGES]


def _resolve_template(template_id, user) -> PromptTemplate | None:
    """Look up a template — own templates AND built-ins (``user IS NULL``).

    Anonymous callers can only address built-in templates.
    """
    if not template_id:
        return None
    qs = PromptTemplate.objects.filter(pk=template_id)
    if user is not None and getattr(user, "is_authenticated", False):
        return qs.filter(user=user).first() or qs.filter(user__isnull=True).first()
    return qs.filter(user__isnull=True).first()


def _provider_error_response(exc: ProviderError) -> Response:
    if isinstance(exc, ProviderRateLimit):
        return Response({"error": str(exc)}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    if isinstance(exc, ProviderAuth):
        return Response({"error": str(exc)}, status=status.HTTP_401_UNAUTHORIZED)
    if isinstance(exc, ProviderUnavailable):
        return Response({"error": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response({"error": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ---------------------------------------------------------------------------
# Generation views
# ---------------------------------------------------------------------------
class GenerateView(APIView):
    """``POST /generate/`` — single-shot generation.

    Accepts ``application/json`` and ``multipart/form-data`` (for image
    uploads). Anonymous users get an auto-created session key.
    """
    permission_classes = (AllowAny,)
    parser_classes = (JSONParser, MultiPartParser, FormParser)

    def post(self, request: Request) -> Response:
        serializer = GenerateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            vision_images = _extract_vision_images(request)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user if request.user.is_authenticated else None
        session_key = "" if user else _resolve_session_key(request)
        template = _resolve_template(data.get("template_id"), user)
        persona = get_persona(user)

        try:
            result = generate(
                user=user,
                session_key=session_key,
                prompt=data.get("prompt", ""),
                persona=persona,
                template=template,
                tone=data.get("tone") or (template.default_tone if template else ""),
                vision_images=vision_images,
                system_prompt=data.get("system_prompt", ""),
                model=data.get("model") or None,
                max_tokens=data.get("max_tokens", 1024),
                temperature=data.get("temperature", 0.7),
                stream=False,
            )
        except ProviderError as exc:
            return _provider_error_response(exc)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "text": result.text,
            "model": result.model,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "cost_usd": str(result.cost_usd),
        })


class StreamingGenerateView(APIView):
    """``POST /generate/stream/`` — server-sent events stream.

    Each chunk arrives as ``data: <text>\\n\\n``. The final event is
    ``event: done\\ndata: {}\\n\\n``.
    """
    permission_classes = (AllowAny,)
    parser_classes = (JSONParser, MultiPartParser, FormParser)

    def post(self, request: Request) -> StreamingHttpResponse | Response:
        serializer = GenerateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            vision_images = _extract_vision_images(request)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user if request.user.is_authenticated else None
        session_key = "" if user else _resolve_session_key(request)
        template = _resolve_template(data.get("template_id"), user)
        persona = get_persona(user)

        try:
            stream = generate(
                user=user,
                session_key=session_key,
                prompt=data.get("prompt", ""),
                persona=persona,
                template=template,
                tone=data.get("tone") or (template.default_tone if template else ""),
                vision_images=vision_images,
                system_prompt=data.get("system_prompt", ""),
                model=data.get("model") or None,
                max_tokens=data.get("max_tokens", 1024),
                temperature=data.get("temperature", 0.7),
                stream=True,
            )
        except ProviderError as exc:
            return _provider_error_response(exc)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        def sse_iter():
            try:
                for chunk in stream:
                    # SSE: escape newlines so multi-line chunks survive parsing.
                    safe = chunk.replace("\n", "\\n")
                    yield f"data: {safe}\n\n"
                yield "event: done\ndata: {}\n\n"
            except ProviderError as exc:
                yield f"event: error\ndata: {exc}\n\n"

        response = StreamingHttpResponse(sse_iter(), content_type="text/event-stream")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"  # disable nginx buffering
        return response


# ---------------------------------------------------------------------------
# Persona view
# ---------------------------------------------------------------------------
class PersonaView(APIView):
    """``GET/PUT /persona/`` — the caller's persona context.

    GET auto-creates an empty persona so the frontend can always render a
    form. PUT performs a partial update.
    """
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        persona, _ = PersonaContext.objects.get_or_create(user=request.user)
        return Response(PersonaContextSerializer(persona).data)

    def put(self, request: Request) -> Response:
        persona, _ = PersonaContext.objects.get_or_create(user=request.user)
        serializer = PersonaContextSerializer(persona, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


# ---------------------------------------------------------------------------
# Template ViewSet
# ---------------------------------------------------------------------------
class TemplateViewSet(viewsets.ModelViewSet):
    """CRUD on user-owned :class:`PromptTemplate` rows.

    Built-in templates (``user IS NULL``) appear in the list but are
    read-only — updates and deletes against them return 403.
    """
    serializer_class = PromptTemplateSerializer
    permission_classes = (IsAuthenticated,)

    def get_queryset(self):
        return list_user_templates(self.request.user).order_by(
            "-is_default", "-updated_at",
        )

    def perform_create(self, serializer):
        is_default = serializer.validated_data.get("is_default", False)
        if is_default:
            PromptTemplate.objects.filter(
                user=self.request.user, is_default=True,
            ).update(is_default=False)
        serializer.save(user=self.request.user)

    def perform_update(self, serializer):
        instance = serializer.instance
        if instance.user_id is None:
            raise PermissionError("Cannot edit a built-in template.")
        if instance.user_id != self.request.user.pk:
            raise PermissionError("Cannot edit someone else's template.")
        is_default = serializer.validated_data.get("is_default", instance.is_default)
        if is_default and not instance.is_default:
            PromptTemplate.objects.filter(
                user=self.request.user, is_default=True,
            ).update(is_default=False)
        serializer.save()

    def perform_destroy(self, instance):
        if instance.user_id is None or instance.user_id != self.request.user.pk:
            raise PermissionError("Cannot delete this template.")
        instance.delete()

    def handle_exception(self, exc):
        if isinstance(exc, PermissionError):
            return Response({"error": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        return super().handle_exception(exc)


# ---------------------------------------------------------------------------
# Generation list view
# ---------------------------------------------------------------------------
class GenerationListView(APIView):
    """``GET /generations/?limit=N`` — most recent generations for the caller."""
    permission_classes = (AllowAny,)

    def get(self, request: Request) -> Response:
        try:
            limit = max(1, min(50, int(request.query_params.get("limit", 10))))
        except (TypeError, ValueError):
            limit = 10
        if request.user.is_authenticated:
            qs = recent_generations(request.user, n=limit)
        else:
            session_key = _resolve_session_key(request)
            qs = recent_generations_for_session(session_key, n=limit)
        return Response(GenerationSerializer(qs, many=True).data)
