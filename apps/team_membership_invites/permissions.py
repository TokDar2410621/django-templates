"""DRF permission classes for team-scoped endpoints.

Usage:

    class MyView(APIView):
        permission_classes = (IsAuthenticated, IsTeamMember)

The view must expose a ``get_team()`` method OR have a ``team`` attribute on
the resolved object — see ``_resolve_team`` below for the lookup order.
"""
from __future__ import annotations

from typing import Optional

from rest_framework.permissions import BasePermission

from .models import Team
from .selectors import is_creator, is_member


def _resolve_team(view, obj=None) -> Optional[Team]:
    """Find the Team this request is scoped to.

    Lookup order:
      1. ``view.get_team()`` if defined (recommended)
      2. ``obj.team`` if the view is operating on a specific object
      3. ``obj`` itself if it's already a Team instance
    """
    if hasattr(view, "get_team"):
        team = view.get_team()
        if team is not None:
            return team
    if obj is not None:
        if isinstance(obj, Team):
            return obj
        team = getattr(obj, "team", None)
        if isinstance(team, Team):
            return team
    return None


class IsTeamMember(BasePermission):
    """Allow any authenticated user who is a member of the resolved team."""

    message = "You are not a member of this team."

    def has_permission(self, request, view) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        team = _resolve_team(view)
        if team is None:
            # Defer to object-level check
            return True
        return is_member(team, request.user)

    def has_object_permission(self, request, view, obj) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        team = _resolve_team(view, obj)
        if team is None:
            return False
        return is_member(team, request.user)


class IsTeamCreator(BasePermission):
    """Allow only the creator of the resolved team."""

    message = "Only the team creator can perform this action."

    def has_permission(self, request, view) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        team = _resolve_team(view)
        if team is None:
            return True
        return is_creator(team, request.user)

    def has_object_permission(self, request, view, obj) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False
        team = _resolve_team(view, obj)
        if team is None:
            return False
        return is_creator(team, request.user)
