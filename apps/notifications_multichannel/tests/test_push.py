"""Web Push tests — degraded mode, 410-gone pruning, PEM unwrap."""
from __future__ import annotations

import pytest

from notifications_multichannel.models import PushSubscription
from notifications_multichannel.services import send_push


@pytest.mark.django_db
def test_push_skipped_without_vapid_keys(user, push_sub, settings):
    settings.VAPID_PUBLIC_KEY = ""
    settings.VAPID_PRIVATE_KEY = ""
    settings.VAPID_ADMIN_EMAIL = ""
    result = send_push(user=user, title="hi", body="hello")
    assert result.status == "skipped"
    assert "VAPID" in result.error


@pytest.mark.django_db
def test_push_skipped_without_admin_email(user, push_sub, vapid_configured):
    vapid_configured.VAPID_ADMIN_EMAIL = ""
    result = send_push(user=user, title="hi", body="hello")
    assert result.status == "skipped"
    assert "VAPID_ADMIN_EMAIL" in result.error


@pytest.mark.django_db
def test_push_sends_to_all_subscriptions(user, push_sub, vapid_configured, mock_webpush):
    # Add a second device
    PushSubscription.objects.create(
        user=user,
        endpoint="https://updates.push.services.mozilla.com/wpush/v2/BBB",
        p256dh="k2", auth="a2",
    )
    result = send_push(user=user, title="hi", body="hello", url="/inbox")
    assert result.ok, result.error
    assert result.meta["delivered"] == 2
    # webpush was called once per subscription
    assert mock_webpush.webpush.call_count == 2


@pytest.mark.django_db
def test_push_prunes_410_gone(user, push_sub, vapid_configured, mock_webpush):
    """A 410 response means the browser uninstalled the SW — purge the row."""
    class FakeResponse:
        status_code = 410

    def raise_410(**kwargs):
        raise mock_webpush.WebPushException("gone", response=FakeResponse())

    mock_webpush.webpush.side_effect = raise_410
    result = send_push(user=user, title="hi", body="hello")
    # No delivery succeeded → skipped, but the row was pruned.
    assert result.status == "skipped"
    assert result.meta["pruned"] == 1
    assert PushSubscription.objects.filter(user=user).count() == 0


@pytest.mark.django_db
def test_push_pem_unwrap(user, push_sub, settings, mock_webpush):
    """``\\n`` escape sequences in the env-var PEM are restored at runtime."""
    settings.VAPID_PUBLIC_KEY = "BPUB"
    settings.VAPID_PRIVATE_KEY = (
        "-----BEGIN PRIVATE KEY-----\\nLINE1\\nLINE2\\n-----END PRIVATE KEY-----"
    )
    settings.VAPID_ADMIN_EMAIL = "admin@example.com"
    send_push(user=user, title="x", body="y")
    sent_priv = mock_webpush.webpush.call_args.kwargs["vapid_private_key"]
    assert "\\n" not in sent_priv  # double-backslash literal absent
    assert "LINE1\nLINE2" in sent_priv


@pytest.mark.django_db
def test_push_no_subscriptions_returns_skipped(user, vapid_configured, mock_webpush):
    result = send_push(user=user, title="hi", body="hello")
    assert result.status == "skipped"
    assert "No active push subscriptions" in result.error
