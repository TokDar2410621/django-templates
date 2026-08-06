"""Pytest fixtures for auth_jwt_oauth.

Assumes the host project has:
- ``rest_framework_simplejwt`` installed
- ``auth_jwt_oauth`` in INSTALLED_APPS with the 0001 migration applied
- DRF's URLconf wired to ``auth_jwt_oauth.urls`` (or equivalent) at
  some prefix — the tests use ``reverse`` so the prefix doesn't matter.
"""
from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.fixture
def api() -> APIClient:
    return APIClient()


@pytest.fixture
def password() -> str:
    return "Sup3rSecret!2026"


@pytest.fixture
def user(db, password: str):
    """A baseline email/password user with a profile attached."""
    from auth_jwt_oauth.services import create_user

    return create_user(
        email="alice@example.com",
        password=password,
        display_name="Alice",
        accept_terms=True,
    )
