"""Permission tests: invite/remove/disband/leave authorization rules."""
from __future__ import annotations

import pytest
from django.test import override_settings

from team_membership_invites.models import Team, TeamMember
from team_membership_invites.services import (
    TeamPermissionError,
    TeamServiceError,
    accept_invite,
    disband,
    invite,
    leave_team,
    remove_member,
)


def _make_member(team, user, creator):
    inv = invite(team=team, email=user.email, invited_by=creator)
    return accept_invite(token=inv.token, user=user)


# ---------------------------------------------------------------------------
# Invite permissions
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_creator_can_invite(team, creator, other_user):
    inv = invite(team=team, email=other_user.email, invited_by=creator)
    assert inv.pk is not None


@pytest.mark.django_db
def test_member_cannot_invite_by_default(team, creator, other_user, third_user):
    _make_member(team, other_user, creator)
    with pytest.raises(TeamPermissionError):
        invite(team=team, email=third_user.email, invited_by=other_user)


@pytest.mark.django_db
@override_settings(TEAM_ALLOW_MEMBER_INVITES=True)
def test_member_can_invite_when_setting_enabled(team, creator, other_user, third_user):
    _make_member(team, other_user, creator)
    inv = invite(team=team, email=third_user.email, invited_by=other_user)
    assert inv.pk is not None


@pytest.mark.django_db
def test_non_member_cannot_invite(team, other_user, third_user):
    # other_user is not a member of `team` (created by `creator`)
    with pytest.raises(TeamPermissionError):
        invite(team=team, email=third_user.email, invited_by=other_user)


# ---------------------------------------------------------------------------
# Remove / leave permissions
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_creator_can_remove_member(team, creator, other_user):
    _make_member(team, other_user, creator)
    remove_member(team=team, user=other_user, by=creator)
    assert not TeamMember.objects.filter(team=team, user=other_user).exists()


@pytest.mark.django_db
def test_member_cannot_remove_other_member(team, creator, other_user, third_user):
    _make_member(team, other_user, creator)
    _make_member(team, third_user, creator)
    with pytest.raises(TeamPermissionError):
        remove_member(team=team, user=third_user, by=other_user)


@pytest.mark.django_db
def test_creator_cannot_be_removed(team, creator, other_user):
    _make_member(team, other_user, creator)
    # other_user is now a regular member; but even creator can't remove themselves.
    with pytest.raises(TeamServiceError, match="creator cannot be removed"):
        remove_member(team=team, user=creator, by=creator)


@pytest.mark.django_db
def test_anyone_can_leave(team, creator, other_user):
    _make_member(team, other_user, creator)
    leave_team(team=team, user=other_user)
    assert not TeamMember.objects.filter(team=team, user=other_user).exists()


@pytest.mark.django_db
def test_creator_cannot_leave(team, creator):
    with pytest.raises(TeamServiceError, match="creator cannot leave"):
        leave_team(team=team, user=creator)


@pytest.mark.django_db
def test_non_member_cannot_leave(team, other_user):
    with pytest.raises(TeamServiceError):
        leave_team(team=team, user=other_user)


# ---------------------------------------------------------------------------
# Disband permissions
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_creator_can_disband(team, creator):
    team_id = team.pk
    disband(team=team, by=creator)
    assert not Team.objects.filter(pk=team_id).exists()


@pytest.mark.django_db
def test_member_cannot_disband(team, creator, other_user):
    _make_member(team, other_user, creator)
    with pytest.raises(TeamPermissionError):
        disband(team=team, by=other_user)
