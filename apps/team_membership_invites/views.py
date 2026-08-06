"""Team REST endpoints.

Views stay thin: validate the request with a serializer, delegate to the
service layer, return the result. Permission rules live in
``services.py`` (defense-in-depth) and ``permissions.py`` (cheap upfront
checks).
"""
from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Team
from .selectors import (
    get_team,
    is_member,
    list_user_teams,
    pending_invites_for_email,
)
from .serializers import (
    AcceptInviteRequestSerializer,
    CreateTeamRequestSerializer,
    InviteRequestSerializer,
    TeamInviteSerializer,
    TeamSerializer,
)
from .services import (
    TeamPermissionError,
    TeamServiceError,
    accept_invite,
    create_team,
    disband,
    invite,
    leave_team,
    remove_member,
    revoke_invite,
)

logger = logging.getLogger(__name__)


def _error_response(exc: TeamServiceError) -> Response:
    """Convert a service-layer error into the right DRF response."""
    code = (
        status.HTTP_403_FORBIDDEN
        if isinstance(exc, TeamPermissionError)
        else status.HTTP_400_BAD_REQUEST
    )
    return Response({"detail": str(exc)}, status=code)


class _TeamScopedMixin:
    """Resolve `team` from `team_id` URL kwarg + check membership."""

    def get_team(self) -> Team | None:
        team_id = self.kwargs.get("team_id") or self.kwargs.get("slug_or_id")
        if team_id is None:
            return None
        return get_team(team_id)

    def _resolve_or_404(self, request):
        team = self.get_team()
        if team is None:
            return None, Response({"detail": "Team not found."}, status=404)
        if not is_member(team, request.user):
            # Treat non-members as 404 to not leak team existence.
            return None, Response({"detail": "Team not found."}, status=404)
        return team, None


class TeamListCreateView(APIView):
    """GET   /teams/      — list teams the caller belongs to
    POST  /teams/      — body: {name, slug?}
    """
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        teams = list_user_teams(request.user)
        return Response(
            TeamSerializer(teams, many=True, context={"request": request}).data
        )

    def post(self, request: Request) -> Response:
        s = CreateTeamRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            team = create_team(
                creator=request.user,
                name=s.validated_data["name"],
                slug=s.validated_data.get("slug") or None,
            )
        except TeamServiceError as exc:
            return _error_response(exc)
        return Response(
            TeamSerializer(team, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class TeamDetailView(_TeamScopedMixin, APIView):
    """GET    /teams/<team_id>/     — full payload (members + invites if creator)
    DELETE /teams/<team_id>/     — disband (creator only)
    """
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, team_id) -> Response:
        team, err = self._resolve_or_404(request)
        if err is not None:
            return err
        return Response(TeamSerializer(team, context={"request": request}).data)

    def delete(self, request: Request, team_id) -> Response:
        team, err = self._resolve_or_404(request)
        if err is not None:
            return err
        try:
            disband(team=team, by=request.user)
        except TeamServiceError as exc:
            return _error_response(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class TeamMembersView(_TeamScopedMixin, APIView):
    """GET /teams/<team_id>/members/ — list members only."""
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, team_id) -> Response:
        team, err = self._resolve_or_404(request)
        if err is not None:
            return err
        return Response(TeamSerializer(team, context={"request": request}).data["members"])


class InviteView(_TeamScopedMixin, APIView):
    """POST /teams/<team_id>/invite/ — body: {email}"""
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, team_id) -> Response:
        team, err = self._resolve_or_404(request)
        if err is not None:
            return err
        s = InviteRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            inv = invite(
                team=team,
                email=s.validated_data["email"],
                invited_by=request.user,
            )
        except TeamServiceError as exc:
            return _error_response(exc)
        return Response(
            TeamInviteSerializer(inv).data, status=status.HTTP_201_CREATED,
        )


class AcceptInviteView(APIView):
    """POST /teams/accept/ — body: {token}"""
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        s = AcceptInviteRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            member = accept_invite(
                token=s.validated_data["token"], user=request.user,
            )
        except TeamServiceError as exc:
            return _error_response(exc)
        return Response(
            TeamSerializer(member.team, context={"request": request}).data
        )


class RevokeInviteView(APIView):
    """POST /teams/invites/<token>/revoke/"""
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, token: str) -> Response:
        try:
            revoke_invite(token=token, by=request.user)
        except TeamServiceError as exc:
            return _error_response(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PendingInvitesView(APIView):
    """GET /teams/invites/pending/ — what's outstanding for my email.

    Surface this right after sign-up so the user sees "you have 2 pending
    team invitations" instead of having to dig out the original email.
    """
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        invites = pending_invites_for_email(request.user.email or "")
        return Response(TeamInviteSerializer(invites, many=True).data)


class LeaveView(_TeamScopedMixin, APIView):
    """POST /teams/<team_id>/leave/"""
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, team_id) -> Response:
        team, err = self._resolve_or_404(request)
        if err is not None:
            return err
        try:
            leave_team(team=team, user=request.user)
        except TeamServiceError as exc:
            return _error_response(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class RemoveMemberView(_TeamScopedMixin, APIView):
    """POST /teams/<team_id>/members/<user_id>/remove/"""
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, team_id, user_id) -> Response:
        team, err = self._resolve_or_404(request)
        if err is not None:
            return err
        from django.contrib.auth import get_user_model

        User = get_user_model()
        try:
            target = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return Response({"detail": "User not found."}, status=404)
        try:
            remove_member(team=team, user=target, by=request.user)
        except TeamServiceError as exc:
            return _error_response(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class DisbandView(_TeamScopedMixin, APIView):
    """POST /teams/<team_id>/disband/ — explicit alias for DELETE /teams/<id>/."""
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, team_id) -> Response:
        team, err = self._resolve_or_404(request)
        if err is not None:
            return err
        try:
            disband(team=team, by=request.user)
        except TeamServiceError as exc:
            return _error_response(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)
