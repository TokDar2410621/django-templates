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
def test_push_prunes_404_gone(user, push_sub, vapid_configured, mock_webpush):
    """Some push services answer 404 (not 410) for an expired subscription."""
    class FakeResponse:
        status_code = 404

    def raise_404(**kwargs):
        raise mock_webpush.WebPushException("not found", response=FakeResponse())

    mock_webpush.webpush.side_effect = raise_404
    result = send_push(user=user, title="hi", body="hello")
    assert result.meta["pruned"] == 1
    assert PushSubscription.objects.filter(user=user).count() == 0


@pytest.mark.django_db
def test_push_pem_converted_for_pywebpush(user, push_sub, vapid_configured, mock_webpush):
    """A PEM key (single-line, literal ``\\n``) reaches pywebpush in a form it can read."""
    from py_vapid import Vapid

    send_push(user=user, title="x", body="y")
    sent_priv = mock_webpush.webpush.call_args.kwargs["vapid_private_key"]
    assert "BEGIN" not in sent_priv
    Vapid.from_string(sent_priv)  # raises on a PEM string: the 1.0.0 bug


@pytest.mark.django_db
def test_push_unreadable_pem_fails_without_sending(user, push_sub, settings, mock_webpush):
    settings.VAPID_PUBLIC_KEY = "BPUB"
    settings.VAPID_PRIVATE_KEY = "-----BEGIN PRIVATE KEY-----\\nLINE1\\n-----END PRIVATE KEY-----"
    settings.VAPID_ADMIN_EMAIL = "admin@example.com"
    result = send_push(user=user, title="x", body="y")
    assert result.status == "failed"
    assert result.error == "VAPID private key unreadable"
    assert mock_webpush.webpush.call_count == 0


@pytest.mark.django_db
def test_push_no_subscriptions_returns_skipped(user, vapid_configured, mock_webpush):
    result = send_push(user=user, title="hi", body="hello")
    assert result.status == "skipped"
    assert "No active push subscriptions" in result.error
