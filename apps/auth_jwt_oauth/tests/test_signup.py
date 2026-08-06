"""Signup endpoint tests."""
from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()


@pytest.mark.django_db
def test_signup_happy_path(api):
    url = reverse("smn_auth:signup")
    resp = api.post(
        url,
        {
            "email": "bob@example.com",
            "password": "Sup3rSecret!2026",
            "display_name": "Bob",
            "accept_terms": True,
        },
        format="json",
    )
    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body["token"]
    assert body["refresh"]
    assert body["user"]["email"] == "bob@example.com"
    assert body["user"]["display_name"] == "Bob"
    assert User.objects.filter(email__iexact="bob@example.com").exists()


@pytest.mark.django_db
def test_signup_rejects_duplicate_email(api, user):
    url = reverse("smn_auth:signup")
    resp = api.post(
        url,
        {
            "email": user.email,
            "password": "Sup3rSecret!2026",
            "display_name": "Alice2",
            "accept_terms": True,
        },
        format="json",
    )
    assert resp.status_code == 400
    assert "email" in resp.json()


@pytest.mark.django_db
def test_signup_requires_terms_acceptance(api):
    url = reverse("smn_auth:signup")
    resp = api.post(
        url,
        {
            "email": "charlie@example.com",
            "password": "Sup3rSecret!2026",
            "display_name": "Charlie",
            "accept_terms": False,
        },
        format="json",
    )
    assert resp.status_code == 400
    assert "accept_terms" in resp.json()


@pytest.mark.django_db
def test_signup_rejects_weak_password(api):
    url = reverse("smn_auth:signup")
    resp = api.post(
        url,
        {
            "email": "dora@example.com",
            "password": "1234",
            "display_name": "Dora",
            "accept_terms": True,
        },
        format="json",
    )
    assert resp.status_code == 400
    assert "password" in resp.json()
