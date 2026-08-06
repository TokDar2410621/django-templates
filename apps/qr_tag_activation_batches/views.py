"""Activation HTTP endpoints.

Public:
    GET  /q/<slug>/                    activation state for a scanned tag

Authenticated:
    POST /api/activation/claim/        redeem a CODE-mode tag
    POST /api/activation/photo-claim/  redeem (or dispute) a PHOTO-mode tag

Staff-only:
    GET  /api/activation/batches/                list batches
    GET  /api/activation/batches/<pk>/           batch detail + stats

Batch generation lives in :mod:`admin` (custom changelist action), not
in the REST API — printing partners shouldn't be able to spawn batches
via HTTP.

Override hook for HTML scan pages
---------------------------------
The default :class:`ScanView` returns JSON so a SPA can render the
"not yet activated" / "claim me" screen client-side. If you'd rather
render server-side HTML, subclass :class:`ScanView`, override ``get``,
and reuse :func:`ScanResponseSerializer.from_code` for the state logic.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ActivationBatch
from .selectors import batch_stats, get_by_slug
from .serializers import (
    ActivationBatchSerializer,
    ClaimRequestSerializer,
    PhotoClaimRequestSerializer,
    ScanResponseSerializer,
)
from .services import (
    AlreadyConsumedError,
    AlreadyDisputedError,
    InvalidActivationError,
    WrongClaimModeError,
    claim_code,
    photo_claim,
)


# ---------------------------------------------------------------------------
# Public scan endpoint
# ---------------------------------------------------------------------------
class ScanView(APIView):
    """``GET /q/<slug>/`` — returns activation state for a scanned tag.

    Public — anonymous because the QR is meant to be scanned by anyone
    holding the physical object. Returns whether the slug is known, the
    claim mode (so the frontend can show the right form), and whether
    it's still claimable.
    """

    permission_classes = (AllowAny,)
    authentication_classes = ()

    def get(self, request: Request, slug: str) -> Response:
        slug = (slug or "").strip().lower()
        code = get_by_slug(slug)
        payload = ScanResponseSerializer.from_code(slug, code)
        return Response(payload)


# ---------------------------------------------------------------------------
# Claim — code mode
# ---------------------------------------------------------------------------
class ClaimView(APIView):
    """``POST /api/activation/claim/`` — redeem a 6-digit code.

    Auth required. The resulting :class:`ActivationCode` row is marked
    consumed by ``request.user``. No domain object is linked by default;
    callers wanting to attach an Item / Sticker / etc. should call
    :func:`services.claim_code` directly from their own view and pass
    ``linked_object=``.
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        serializer = ClaimRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            code = claim_code(
                user=request.user,
                qr_slug=serializer.validated_data["qr_slug"],
                activation_code=serializer.validated_data["activation_code"],
            )
        except InvalidActivationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except WrongClaimModeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except AlreadyConsumedError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)

        return Response(
            {
                "qr_slug": code.qr_slug,
                "consumed_at": code.consumed_at,
                "claim_status": code.claim_status,
            },
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Claim — photo mode
# ---------------------------------------------------------------------------
# Inline guards mirror typical photo limits so the guard fires BEFORE the
# service spends a DB transaction on a bad upload. Override by subclassing
# or by tweaking your DRF parser limits.
_MAX_PHOTO_BYTES = 10 * 1024 * 1024
_ALLOWED_PHOTO_MIME = {"image/png", "image/jpeg", "image/webp", "image/gif"}


class PhotoClaimView(APIView):
    """``POST /api/activation/photo-claim/`` — multipart form.

    First claim on a PHOTO-mode tag marks the code PROVISIONAL and stores
    the proof photo. Subsequent claims during the provisional window
    create :class:`OwnershipDispute` rows for admin review.

    Returns 201 on first claim, 202 with ``{dispute_filed: true}`` on
    subsequent claims during the window.
    """

    permission_classes = (IsAuthenticated,)
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request: Request) -> Response:
        serializer = PhotoClaimRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        photo = serializer.validated_data["photo"]

        if getattr(photo, "size", 0) > _MAX_PHOTO_BYTES:
            return Response(
                {
                    "photo": [
                        f"Photo too large (max {_MAX_PHOTO_BYTES // (1024 * 1024)} MB).",
                    ],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        ct = getattr(photo, "content_type", "") or ""
        if ct and ct not in _ALLOWED_PHOTO_MIME:
            return Response(
                {"photo": [f"Unsupported file type ({ct}). Use PNG, JPG, WEBP, GIF."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            code, was_first = photo_claim(
                user=request.user,
                qr_slug=serializer.validated_data["qr_slug"],
                photo=photo,
                message=serializer.validated_data.get("message", ""),
            )
        except InvalidActivationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except WrongClaimModeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except AlreadyConsumedError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except AlreadyDisputedError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)

        if was_first:
            return Response(
                {
                    "qr_slug": code.qr_slug,
                    "consumed_at": code.consumed_at,
                    "claim_status": code.claim_status,
                    "is_provisional": True,
                    "provisional_until": code.provisional_until,
                },
                status=status.HTTP_201_CREATED,
            )

        return Response(
            {
                "detail": "Your dispute has been filed. An admin will review.",
                "dispute_filed": True,
                "code_id": code.pk,
            },
            status=status.HTTP_202_ACCEPTED,
        )


# ---------------------------------------------------------------------------
# Admin / staff read endpoints
# ---------------------------------------------------------------------------
class BatchListView(ListAPIView):
    """``GET /api/activation/batches/`` — staff-only list of batches."""

    permission_classes = (IsAdminUser,)
    serializer_class = ActivationBatchSerializer
    queryset = ActivationBatch.objects.all().order_by("-created_at")


class BatchDetailView(RetrieveAPIView):
    """``GET /api/activation/batches/<pk>/`` — batch + computed stats."""

    permission_classes = (IsAdminUser,)
    serializer_class = ActivationBatchSerializer
    queryset = ActivationBatch.objects.all()

    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        instance = self.get_object()
        data = self.get_serializer(instance).data
        data["stats"] = batch_stats(instance)
        return Response(data)
