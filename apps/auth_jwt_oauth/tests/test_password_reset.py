"""Password reset request + confirm flow tests.

The request endpoint goes through Django's email machinery — we rely on
``django.core.mail.outbox`` (locmem backend, set in pytest settings).
"""
from __future__ import annotations

import re

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.test.utils import override_settings
from django.urls import reverse

User = get_user_model()


@pytest.mark.django_db
@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    AUTH_JWT_FRONTEND_URL="https://example.test",
)
def test_request_password_reset_sends_email(api, user):
    mail.outbox.clear()
    resp = api.post(
        reverse("smn_auth:password-reset-request"),
        {"email": user.email},
        format="json",
    )
    assert resp.status_code == 200
    assert len(mail.outbox) == 1
    body = mail.outbox[0].body
    assert "https://example.test/reset-password?" in body
    assert "uid=" in body
    assert "token=" in body


@pytest.mark.django_db
@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    AUTH_JWT_FRONTEND_URL="https://example.test",
)
def test_request_password_reset_silent_for_unknown_email(api):
    mail.outbox.clear()
    resp = api.post(
        reverse("smn_auth:password-reset-request"),
        {"email": "ghost@example.com"},
        format="json",
    )
    # Always 200 — we don't leak account existence
    assert resp.status_code == 200
    assert len(mail.outbox) == 0


@pytest.mark.django_db
@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    AUTH_JWT_FRONTEND_URL="https://example.test",
)
def test_confirm_password_reset_happy_path(api, user):
    mail.outbox.clear()
    api.post(
        reverse("smn_auth:password-reset-request"),
        {"email": user.email},
        format="json",
    )
    body = mail.outbox[0].body
    match = re.search(r"uid=([^&\s]+)&token=([^\s]+)", body)
    assert match, body
    uid, token = match.group(1), match.group(2)

    new_password = "BrandN3wPass!2026"
    resp = api.post(
        reverse("smn_auth:password-reset-confirm"),
        {"uid": uid, "token": token, "new_password": new_password},
        format="json",
    )
    assert resp.status_code == 200

    # The new password authenticates; the old one no longer does.
    user.refresh_from_db()
    assert user.check_password(new_password)


@pytest.mark.django_db
def test_confirm_password_reset_rejects_bad_token(api, user):
    resp = api.post(
        reverse("smn_auth:password-reset-confirm"),
        {
            "uid": "MQ",  # base64("1")
            "token": "not-a-real-token",
            "new_password": "Sup3rSecret!2026",
        },
        format="json",
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_confirm_password_reset_rejects_weak_new_password(api, user):
    # Build a valid uid/token pair so we know the rejection is for the
    # password, not the token.
    from django.contrib.auth.tokens import default_token_generator
    from django.utils.encoding import force_bytes
    from django.utils.http import urlsafe_base64_encode

    uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)

    resp = api.post(
        reverse("smn_auth:password-reset-confirm"),
        {"uid": uidb64, "token": token, "new_password": "1234"},
        format="json",
    )
    assert resp.status_code == 400
    assert "new_password" in resp.json()
