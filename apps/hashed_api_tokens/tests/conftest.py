from __future__ import annotations

import sys
import types

import pytest
from django.contrib.auth import get_user_model
from django.urls import include, path
from rest_framework.test import APIClient


@pytest.fixture
def user(db):
    User = get_user_model()
    return User.objects.create_user(
        username="alice",
        email="alice@example.com",
        password="pwpwpwpw",
    )


@pytest.fixture
def other_user(db):
    User = get_user_model()
    return User.objects.create_user(
        username="bob",
        email="bob@example.com",
        password="pwpwpwpw",
    )


@pytest.fixture(autouse=True)
def _token_urls(settings):
    """Auto-mount ``/api/tokens/`` for every test so the management endpoints
    are reachable even when running in isolation (no host project urlconf).

    Tests that need a different urlconf (see ``test_auth.py::probe_urls``)
    override ``settings.ROOT_URLCONF`` themselves and win.
    """
    module = types.ModuleType("hashed_api_tokens_test_urls")
    module.urlpatterns = [
        path("api/tokens/", include("hashed_api_tokens.urls")),
    ]
    sys.modules["hashed_api_tokens_test_urls"] = module
    settings.ROOT_URLCONF = "hashed_api_tokens_test_urls"
    yield
    sys.modules.pop("hashed_api_tokens_test_urls", None)


@pytest.fixture
def api() -> APIClient:
    return APIClient()
