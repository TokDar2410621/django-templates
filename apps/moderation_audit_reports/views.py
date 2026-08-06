"""Moderation API — public submit + staff-only triage/ban.

Routes (see ``urls.py`` for exact paths):

    POST   /api/moderation/reports/                  authenticated  submit a report
    GET    /api/moderation/admin/reports/            staff          list queue
    GET    /api/moderation/admin/reports/<id>/       staff          report detail
    PATCH  /api/moderation/admin/reports/<id>/triage/   staff       triage status
    POST   /api/moderation/admin/users/<user_id>/ban/   staff       ban a user
    POST   /api/moderation/admin/users/<user_id>/unban/ staff       lift a ban

Permissions:
    * Submit  — ``IsAuthenticated`` (we want a reporter trail; if you
                support anonymous reports, swap to ``AllowAny`` and
                ``submit_report`` will pass ``reporter=None``).
    * Admin   — ``IsAdminUser`` (i.e. ``user.is_staff``). Non-staff get
                403 (NOT 404) so a frontend AdminGuard can redirect them.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import status as http_status
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Report
from .selectors import is_banned, report_queue
from .serializers import (
    BanUserInputSerializer,
    ReportDetailSerializer,
    ReportListSerializer,
    ReportSubmitSerializer,
    TriageInputSerializer,
)
from .services import ban_user, submit_report, triage_report, unban_user


User = get_user_model()


# ---------------------------------------------------------------------------
# Public — submit a report
# ---------------------------------------------------------------------------
class ReportSubmitView(APIView):
    """POST /api/moderation/reports/ — file a content report."""

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        ser = ReportSubmitSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        target_owner = None
        owner_id = data.get("target_owner_id") or ""
        if owner_id:
            try:
                target_owner = User.objects.get(pk=int(owner_id))
            except (User.DoesNotExist, ValueError, TypeError):
                target_owner = None

        # Refuse reports filed by a banned user — they're not entitled
        # to mod resources, and it limits brigading abuse.
        if is_banned(request.user):
            return Response(
                {"detail": "Banned users cannot file reports."},
                status=http_status.HTTP_403_FORBIDDEN,
            )

        report = submit_report(
            reporter=request.user,
            target_type=data["target_type"],
            target_id=data["target_id"],
            target_owner=target_owner,
            reason=data["reason"],
            description=data.get("description", ""),
            evidence_url=data.get("evidence_url", ""),
        )
        return Response(
            {"id": report.pk, "priority": report.priority},
            status=http_status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Admin — list / detail / triage
# ---------------------------------------------------------------------------
class AdminReportListView(APIView):
    """GET /api/moderation/admin/reports/?status=open&priority=3&target_type=message"""

    permission_classes = (IsAdminUser,)

    def get(self, request: Request) -> Response:
        qs = report_queue(
            status=request.query_params.get("status") or "open",
            priority=_int_or_none(request.query_params.get("priority")),
            target_type=request.query_params.get("target_type") or None,
        )[: _page_limit(request)]
        return Response(ReportListSerializer(qs, many=True).data)


class AdminReportDetailView(APIView):
    """GET /api/moderation/admin/reports/<id>/"""

    permission_classes = (IsAdminUser,)

    def get(self, request: Request, report_id: int) -> Response:
        report = get_object_or_404(Report, pk=report_id)
        return Response(ReportDetailSerializer(report).data)


class AdminTriageView(APIView):
    """PATCH /api/moderation/admin/reports/<id>/triage/ — change status."""

    permission_classes = (IsAdminUser,)

    def patch(self, request: Request, report_id: int) -> Response:
        report = get_object_or_404(Report, pk=report_id)
        ser = TriageInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        triage_report(
            report=report,
            actor=request.user,
            status=ser.validated_data["status"],
            note=ser.validated_data.get("note", ""),
        )
        return Response(ReportDetailSerializer(report).data)


# ---------------------------------------------------------------------------
# Admin — ban / unban
# ---------------------------------------------------------------------------
class AdminBanUserView(APIView):
    """POST /api/moderation/admin/users/<user_id>/ban/

    Bans the target user. Returns 403 if the target is a staff user
    (you don't ban admins through the API — go through the Django
    admin Users page if you really need to).
    """

    permission_classes = (IsAdminUser,)

    def post(self, request: Request, user_id: int) -> Response:
        user = get_object_or_404(User, pk=user_id)
        if getattr(user, "is_staff", False):
            return Response(
                {"detail": "Cannot ban a staff user via the API."},
                status=http_status.HTTP_403_FORBIDDEN,
            )
        ser = BanUserInputSerializer(data=request.data or {})
        ser.is_valid(raise_exception=True)
        ban_user(
            user=user,
            by=request.user,
            reason=ser.validated_data.get("reason", ""),
            days=ser.validated_data.get("days"),
        )
        return Response(
            {"id": user.pk, "is_banned": True},
            status=http_status.HTTP_200_OK,
        )


class AdminUnbanUserView(APIView):
    """POST /api/moderation/admin/users/<user_id>/unban/"""

    permission_classes = (IsAdminUser,)

    def post(self, request: Request, user_id: int) -> Response:
        user = get_object_or_404(User, pk=user_id)
        unban_user(
            user=user,
            by=request.user,
            note=(request.data or {}).get("note", ""),
        )
        return Response(
            {"id": user.pk, "is_banned": False},
            status=http_status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _int_or_none(v) -> int | None:
    try:
        return int(v) if v is not None and v != "" else None
    except (ValueError, TypeError):
        return None


def _page_limit(request: Request, default: int = 200, hard_cap: int = 1000) -> int:
    try:
        n = int(request.query_params.get("limit", default))
    except (ValueError, TypeError):
        n = default
    return max(1, min(n, hard_cap))
