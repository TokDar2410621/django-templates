"""Test fixtures.

The tests expect the project's ``settings`` to define:

    SAAS_PLAN_LIMITS = {
        "free":   {"article_generation": 1,   "api_call": 100},
        "solo":   {"article_generation": 8,   "api_call": 1000},
        "pro":    {"article_generation": 60,  "api_call": None},  # unlimited
        "agency": {"article_generation": 200, "api_call": None},
    }
    SAAS_DEFAULT_PLAN = "free"

If your project ships different defaults, override with
``@pytest.mark.django_db`` + ``settings.SAAS_PLAN_LIMITS = {...}`` at the
top of each test (see ``test_consume.py`` for an example).
"""
from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from saas_billing_credits_quota.selectors import get_or_create_subscription


@pytest.fixture
def user(db):
    User = get_user_model()
    return User.objects.create_user(
        username="billtester",
        email="billtester@example.com",
        password="pwpwpwpw",
    )


@pytest.fixture
def other_user(db):
    User = get_user_model()
    return User.objects.create_user(
        username="otherbiller",
        email="otherbiller@example.com",
        password="pwpwpwpw",
    )


@pytest.fixture
def plan_limits(settings):
    """Inject a deterministic SAAS_PLAN_LIMITS for the tests."""
    settings.SAAS_PLAN_LIMITS = {
        "free":   {"article_generation": 1,   "api_call": 100},
        "solo":   {"article_generation": 8,   "api_call": 1000},
        "pro":    {"article_generation": 60,  "api_call": None},
        "agency": {"article_generation": 200, "api_call": None},
    }
    settings.SAAS_DEFAULT_PLAN = "free"
    return settings.SAAS_PLAN_LIMITS


@pytest.fixture
def free_user(user, plan_limits):
    """A user with a freshly-created free subscription + 0 credits."""
    get_or_create_subscription(user)
    return user
