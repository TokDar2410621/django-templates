"""Login + me + logout tests."""
from __future__ import annotations

import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_login_happy_path(api, user, password):
    url = reverse("smn_auth:login")
    resp = api.post(
        url,
        {"email": user.email, "password": password},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["token"]
    assert body["refresh"]
    assert body["user"]["email"] == user.email


@pytest.mark.django_db
def test_login_rejects_wrong_password(api, user):
    url = reverse("smn_auth:login")
    resp = api.post(
        url,
        {"email": user.email, "password": "nope-nope-nope"},
        format="json",
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_login_rejects_banned_account(api, user, password):
    from auth_jwt_oauth.models import UserProfile

    UserProfile.objects.filter(user=user).update(is_banned=True)

    url = reverse("smn_auth:login")
    resp = api.post(
        url,
        {"email": user.email, "password": password},
        format="json",
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_me_requires_auth(api):
    resp = api.get(reverse("smn_auth:me"))
    assert resp.status_code == 401


@pytest.mark.django_db
def test_me_returns_user_shape(api, user, password):
    login_resp = api.post(
        reverse("smn_auth:login"),
        {"email": user.email, "password": password},
        format="json",
    )
    token = login_resp.json()["token"]
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    resp = api.get(reverse("smn_auth:me"))
    assert resp.status_code == 200
    assert resp.json()["email"] == user.email


@pytest.mark.django_db
def test_check_email_returns_true_for_existing(api, user):
    resp = api.post(
        reverse("smn_auth:check-email"),
        {"email": user.email},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.json() == {"exists": True}


@pytest.mark.django_db
def test_check_email_returns_false_for_unknown(api):
    resp = api.post(
        reverse("smn_auth:check-email"),
        {"email": "ghost@example.com"},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.json() == {"exists": False}


@pytest.mark.django_db
def test_logout_blacklists_refresh_token(api, user, password):
    login_resp = api.post(
        reverse("smn_auth:login"),
        {"email": user.email, "password": password},
        format="json",
    )
    refresh = login_resp.json()["refresh"]
    token = login_resp.json()["token"]

    api.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    resp = api.post(
        reverse("smn_auth:logout"),
        {"refresh": refresh},
        format="json",
    )
    assert resp.status_code == 204
