"""Tests for team creation."""
from __future__ import annotations

import pytest

from team_membership_invites.models import ROLE_CREATOR, Team, TeamMember
from team_membership_invites.selectors import list_user_teams
from team_membership_invites.services import TeamServiceError, create_team


@pytest.mark.django_db
def test_create_team_inserts_team_and_creator_membership(creator):
    team = create_team(creator=creator, name="Acme")
    assert team.pk is not None
    assert team.creator_id == creator.id
    # The creator is automatically a member with role=creator.
    member = TeamMember.objects.get(team=team, user=creator)
    assert member.role == ROLE_CREATOR


@pytest.mark.django_db
def test_create_team_empty_name_rejected(creator):
    with pytest.raises(TeamServiceError):
        create_team(creator=creator, name="   ")


@pytest.mark.django_db
def test_create_team_truncates_long_name(creator):
    long_name = "x" * 200
    team = create_team(creator=creator, name=long_name)
    assert len(team.name) == 80


@pytest.mark.django_db
def test_create_team_with_slug(creator):
    team = create_team(creator=creator, name="Acme", slug="acme")
    assert team.slug == "acme"


@pytest.mark.django_db
def test_list_user_teams_excludes_non_member_teams(creator, other_user):
    create_team(creator=creator, name="Mine")
    create_team(creator=other_user, name="Theirs")
    teams = list(list_user_teams(creator))
    assert len(teams) == 1
    assert teams[0].name == "Mine"
