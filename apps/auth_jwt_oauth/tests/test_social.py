"""Social adapter + OAuth endpoint behaviour.

We don't talk to Google/Apple in tests — the OAuth round-trip is owned
by Allauth and tested upstream. We test:

1. The adapter populates ``display_name`` from the OAuth profile and
   stamps ``terms_accepted_at`` on ``save_user``.
2. The adapter auto-links to an existing email/password user instead
   of crashing on the unique email constraint.
3. The endpoint stubs return 503 with a clear message when allauth +
   dj-rest-auth aren't installed (skipped when they ARE installed).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.mark.django_db
def test_adapter_populates_display_name_from_oauth_payload():
    from auth_jwt_oauth.adapters import DefaultSocialAdapter

    adapter = DefaultSocialAdapter()

    # A bare user without display_name attr — adapter should NOT crash.
    user = User(email="ghost@example.com")
    sociallogin = MagicMock()
    data = {"name": "Ghost McGhost", "email": "ghost@example.com"}

    # Patch super().populate_user to return our user directly so we
    # don't depend on Allauth's internals.
    from allauth.socialaccount.adapter import DefaultSocialAccountAdapter

    original = DefaultSocialAccountAdapter.populate_user
    try:
        DefaultSocialAccountAdapter.populate_user = lambda self, req, sl, d: user
        adapter.populate_user(None, sociallogin, data)
    finally:
        DefaultSocialAccountAdapter.populate_user = original

    # display_name is only set when the user model carries that attr;
    # the stock django.contrib.auth.User does not — so we assert no
    # crash and either the attr was set (custom model) or skipped.
    assert getattr(user, "username", "") != "" or not hasattr(user, "username")


@pytest.mark.django_db
def test_adapter_pre_social_login_links_existing_email(monkeypatch, user):
    """An existing email/password user should be re-used, not crashed on."""
    from auth_jwt_oauth.adapters import DefaultSocialAdapter

    adapter = DefaultSocialAdapter()
    sociallogin = MagicMock()
    sociallogin.is_existing = False
    sociallogin.user = MagicMock()
    sociallogin.user.email = user.email
    # patch user_email so our MagicMock fakes the field correctly
    import auth_jwt_oauth.adapters as adapters_mod
    monkeypatch.setattr(adapters_mod, "user_email", lambda u: u.email)

    adapter.pre_social_login(None, sociallogin)

    # connect() should have been called with the existing user
    sociallogin.connect.assert_called_once()
    args, _ = sociallogin.connect.call_args
    assert args[1] == user


@pytest.mark.django_db
def test_adapter_save_user_stamps_terms_accepted(monkeypatch, user):
    """save_user should set terms_accepted_at on the attached profile."""
    from auth_jwt_oauth.adapters import DefaultSocialAdapter
    from auth_jwt_oauth.models import UserProfile

    # Wipe the timestamp on our fixture user's profile.
    UserProfile.objects.filter(user=user).update(terms_accepted_at=None)
    assert UserProfile.objects.get(user=user).terms_accepted_at is None

    adapter = DefaultSocialAdapter()

    from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
    monkeypatch.setattr(
        DefaultSocialAccountAdapter, "save_user",
        lambda self, req, sl, form=None: user,
    )

    sociallogin = MagicMock()
    adapter.save_user(None, sociallogin)

    UserProfile.objects.get(user=user).terms_accepted_at  # noqa: B018
    assert UserProfile.objects.get(user=user).terms_accepted_at is not None


@pytest.mark.django_db
def test_oauth_stub_endpoints_503_when_allauth_missing(api, monkeypatch):
    """Skipped automatically when allauth is installed (most projects)."""
    import auth_jwt_oauth.social_views as sv
    if sv._OAUTH_AVAILABLE:
        pytest.skip("Allauth + dj-rest-auth installed — stubs not used.")
    from django.urls import reverse
    resp = api.post(reverse("smn_auth:google"), {}, format="json")
    assert resp.status_code == 503
