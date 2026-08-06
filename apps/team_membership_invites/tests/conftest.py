"""Pytest fixtures for team_membership_invites tests."""
from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from team_membership_invites.models import Team
from team_membership_invites.services import create_team


User = get_user_model()


@pytest.fixture
def creator(db):
    return User.objects.create_user(
        username="creator",
        email="creator@example.com",
        password="pwpwpwpw",
    )


@pytest.fixture
def other_user(db):
    return User.objects.create_user(
        username="other",
        email="other@example.com",
        password="pwpwpwpw",
    )


@pytest.fixture
def third_user(db):
    return User.objects.create_user(
        username="third",
        email="third@example.com",
        password="pwpwpwpw",
    )


@pytest.fixture
def team(db, creator) -> Team:
    return create_team(creator=creator, name="Acme")
