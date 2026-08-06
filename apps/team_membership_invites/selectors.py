"""Read-only queries for team_membership_invites.

Keep ALL read paths here so views/serializers never reach into the ORM
themselves. Makes it easy to add caching or denormalize later in one place.
"""
from __future__ import annotations

from typing import Iterable, Optional, Union

from django.db.models import QuerySet
from django.utils import timezone

from .models import Team, TeamInvite, TeamMember


def get_team(slug_or_id: Union[str, int]) -> Optional[Team]:
    """Fetch a team by primary key OR slug. Returns None if not found."""
    if isinstance(slug_or_id, int) or (
        isinstance(slug_or_id, str) and slug_or_id.isdigit()
    ):
        return Team.objects.filter(pk=int(slug_or_id)).first()
    return Team.objects.filter(slug=slug_or_id).first()


def list_user_teams(user) -> QuerySet[Team]:
    """All teams the user is a member of, newest first."""
    return (
        Team.objects.filter(members__user=user)
        .order_by("-created_at")
        .distinct()
    )


def list_team_members(team: Team) -> QuerySet[TeamMember]:
    """Members of a team, oldest first (creator is always first by design)."""
    return (
        TeamMember.objects.filter(team=team)
        .select_related("user")
        .order_by("joined_at")
    )


def is_member(team: Team, user) -> bool:
    """Cheap membership check."""
    return TeamMember.objects.filter(team=team, user=user).exists()


def is_creator(team: Team, user) -> bool:
    return team.creator_id == user.id


def pending_invites_for_team(team: Team) -> QuerySet[TeamInvite]:
    """Outstanding (un-accepted, un-revoked, un-expired) invites for a team."""
    return (
        TeamInvite.objects.filter(
            team=team,
            accepted_at__isnull=True,
            revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
        .order_by("-created_at")
    )


def pending_invites_for_email(email: str) -> QuerySet[TeamInvite]:
    """All pending invites currently outstanding for a recipient email.

    Useful right after sign-up to surface "you have N pending invites".
    """
    email = (email or "").strip().lower()
    if not email:
        return TeamInvite.objects.none()
    return (
        TeamInvite.objects.filter(
            email__iexact=email,
            accepted_at__isnull=True,
            revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
        .select_related("team", "invited_by")
        .order_by("-created_at")
    )
