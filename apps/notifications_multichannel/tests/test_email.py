"""Email channel tests — degraded mode, role-based senders, template rendering."""
from __future__ import annotations

import pytest

from notifications_multichannel.models import NotificationLog
from notifications_multichannel.services import send_email


@pytest.mark.django_db
def test_email_skipped_when_no_api_key(user, settings):
    settings.RESEND_API_KEY = ""
    result = send_email(
        user=user,
        role="notification",
        subject="Hi",
        html="<p>Hi</p>",
    )
    assert result.status == "skipped"
    assert "RESEND_API_KEY" in result.error
    # The log row still records the attempt.
    log = NotificationLog.objects.first()
    assert log is not None
    assert log.status == "skipped"
    assert log.channel == "email"


@pytest.mark.django_db
def test_email_uses_role_based_sender(user, resend_configured, mock_requests_post):
    result = send_email(
        user=user,
        role="orders",
        subject="Order #42",
        html="<p>Thanks for your order.</p>",
    )
    assert result.ok, result.error
    payload = mock_requests_post.call_args.kwargs["json"]
    assert payload["from"] == "orders@example.com"
    # Reply-To for the "orders" role is set in the fixture
    assert payload["reply_to"] == ["support@example.com"]


@pytest.mark.django_db
def test_email_falls_back_to_RESEND_FROM_EMAIL(user, resend_configured, mock_requests_post):
    # Wipe role senders to force the generic fallback path
    resend_configured.RESEND_SENDERS = {}
    result = send_email(
        user=user, role="notification",
        subject="Hi", html="<p>Hi</p>",
    )
    assert result.ok
    payload = mock_requests_post.call_args.kwargs["json"]
    assert payload["from"] == "fallback@example.com"


@pytest.mark.django_db
def test_email_failed_when_no_destination(resend_configured, mock_requests_post):
    """No ``to`` and no ``user.email`` → fail with a clear error."""
    result = send_email(
        role="notification",
        subject="Hi",
        html="<p>Hi</p>",
    )
    assert result.status == "failed"
    assert "destination" in result.error


@pytest.mark.django_db
def test_email_uses_explicit_to_over_user(user, resend_configured, mock_requests_post):
    result = send_email(
        user=user,
        to="override@example.com",
        role="notification",
        subject="Hi",
        html="<p>Hi</p>",
    )
    assert result.ok
    payload = mock_requests_post.call_args.kwargs["json"]
    assert payload["to"] == ["override@example.com"]


@pytest.mark.django_db
def test_email_returns_failed_on_4xx(user, resend_configured, monkeypatch):
    from unittest.mock import MagicMock
    fake = MagicMock()
    fake.return_value.status_code = 422
    fake.return_value.text = "domain unverified"
    monkeypatch.setattr(
        "notifications_multichannel.backends.email_resend.requests.post", fake,
    )
    result = send_email(
        user=user, role="notification",
        subject="x", html="<p>x</p>",
    )
    assert result.status == "failed"
    assert "422" in result.error
