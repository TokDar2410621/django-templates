"""Shared fixtures + SDK mocks for notifications_multichannel tests.

All three providers (Resend, pywebpush, Twilio) hit the network. We mock
them at the backend boundary so tests stay hermetic and fast.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from django.contrib.auth import get_user_model

from notifications_multichannel.models import PushSubscription


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
@pytest.fixture
def user(db):
    User = get_user_model()
    return User.objects.create_user(
        username="notifuser",
        email="notifuser@example.com",
        password="pwpwpwpw",
    )


@pytest.fixture
def admin_user(db):
    User = get_user_model()
    return User.objects.create_superuser(
        username="notifadmin",
        email="notifadmin@example.com",
        password="pwpwpwpw",
    )


@pytest.fixture
def push_sub(db, user) -> PushSubscription:
    return PushSubscription.objects.create(
        user=user,
        endpoint="https://fcm.googleapis.com/fcm/send/AAAA-fixture",
        p256dh="p256dh-fixture",
        auth="auth-fixture",
        user_agent="pytest/1.0",
    )


# ---------------------------------------------------------------------------
# Settings (degraded vs configured)
# ---------------------------------------------------------------------------
@pytest.fixture
def resend_configured(settings):
    settings.RESEND_API_KEY = "test-resend-key"
    settings.RESEND_FROM_EMAIL = "fallback@example.com"
    settings.RESEND_SENDERS = {
        "noreply": "noreply@example.com",
        "notification": "notification@example.com",
        "orders": "orders@example.com",
    }
    settings.RESEND_REPLY_TO = {
        "noreply": "",
        "notification": "",
        "orders": "support@example.com",
    }
    return settings


@pytest.fixture
def vapid_configured(settings):
    # PEM is single-line with \\n placeholders — the backend un-escapes them.
    settings.VAPID_PUBLIC_KEY = "BPUBKEY"
    settings.VAPID_PRIVATE_KEY = "-----BEGIN PRIVATE KEY-----\\nfake\\n-----END PRIVATE KEY-----"
    settings.VAPID_ADMIN_EMAIL = "admin@example.com"
    return settings


@pytest.fixture
def twilio_configured(settings):
    settings.TWILIO_ACCOUNT_SID = "AC_test"
    settings.TWILIO_AUTH_TOKEN = "twilio-token"
    settings.TWILIO_FROM_NUMBER = "+15550000000"
    return settings


# ---------------------------------------------------------------------------
# SDK mocks
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_requests_post(monkeypatch):
    """Patch ``requests.post`` used by the Resend backend."""
    mock = MagicMock()
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.text = '{"id": "resend-msg-1"}'
    fake_response.json.return_value = {"id": "resend-msg-1"}
    mock.return_value = fake_response
    monkeypatch.setattr(
        "notifications_multichannel.backends.email_resend.requests.post",
        mock,
    )
    return mock


@pytest.fixture
def mock_webpush(monkeypatch):
    """Patch the ``pywebpush.webpush`` symbol imported lazily."""
    import sys
    import types

    # Build a fake pywebpush module so the lazy `from pywebpush import ...`
    # in the backend resolves to our mock without needing the real package.
    fake_module = types.ModuleType("pywebpush")
    fake_module.webpush = MagicMock(return_value=None)

    class WebPushException(Exception):
        def __init__(self, message="", response=None):
            super().__init__(message)
            self.response = response

    fake_module.WebPushException = WebPushException
    monkeypatch.setitem(sys.modules, "pywebpush", fake_module)
    return fake_module


@pytest.fixture
def mock_twilio(monkeypatch):
    """Patch the ``twilio.rest.Client`` used inside the SMS backend."""
    import sys
    import types

    fake_twilio = types.ModuleType("twilio")
    fake_twilio_rest = types.ModuleType("twilio.rest")

    class FakeMessage:
        def __init__(self, sid: str = "twilio-msg-1"):
            self.sid = sid

    class FakeMessages:
        def __init__(self):
            self.created: list[dict] = []

        def create(self, **kwargs):
            self.created.append(kwargs)
            return FakeMessage()

    class FakeClient:
        def __init__(self, sid, token):
            self.sid = sid
            self.token = token
            self.messages = FakeMessages()

    fake_twilio_rest.Client = FakeClient
    monkeypatch.setitem(sys.modules, "twilio", fake_twilio)
    monkeypatch.setitem(sys.modules, "twilio.rest", fake_twilio_rest)
    return FakeClient
