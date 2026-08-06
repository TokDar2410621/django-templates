"""Webhook signature verification + event dispatch tests."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest
from rest_framework.test import APIClient

from newsletter_engine.models import (
    BounceEvent,
    Campaign,
    Delivery,
    Subscriber,
)
from newsletter_engine.services.campaigns import create_campaign, fan_out
from newsletter_engine.services.subscribers import add_to_list


# ---------------------------------------------------------------------------
# Signature helpers — match the simplified Svix-style scheme in views.py.
# ---------------------------------------------------------------------------
def _sign(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return "v1," + base64.b64encode(digest).decode("ascii")


@pytest.fixture
def configured_webhook(settings):
    settings.NEWSLETTER_RESEND_WEBHOOK_SECRET = "test-secret"
    return settings.NEWSLETTER_RESEND_WEBHOOK_SECRET


@pytest.fixture
def delivered_delivery(tenant, mailing_list, confirmed_subscriber):
    add_to_list(confirmed_subscriber, mailing_list)
    camp = create_campaign(
        tenant=tenant, target=mailing_list,
        subject="X", html_body="<p>x</p>",
    )
    Campaign.objects.filter(pk=camp.pk).update(status=Campaign.STATUS_SENDING)
    camp.refresh_from_db()
    fan_out(camp)
    delivery = Delivery.objects.get(campaign=camp)
    Delivery.objects.filter(pk=delivery.pk).update(provider_message_id="msg_test_123")
    delivery.refresh_from_db()
    return delivery


@pytest.mark.django_db
def test_webhook_missing_secret_returns_503(db):
    """When the secret env isn't set, return 503 rather than crashing."""
    api = APIClient()
    resp = api.post(
        "/api/newsletter/webhooks/resend/", data={}, format="json",
    )
    assert resp.status_code == 503


@pytest.mark.django_db
def test_webhook_bad_signature_returns_400(configured_webhook):
    api = APIClient()
    body = json.dumps({"type": "email.delivered"}).encode("utf-8")
    resp = api.post(
        "/api/newsletter/webhooks/resend/",
        data=body, content_type="application/json",
        HTTP_SVIX_SIGNATURE="v1,obviously-wrong",
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_webhook_delivered_marks_delivery(configured_webhook, delivered_delivery):
    api = APIClient()
    event = {
        "type": "email.delivered",
        "data": {"email_id": "msg_test_123"},
    }
    body = json.dumps(event).encode("utf-8")
    resp = api.post(
        "/api/newsletter/webhooks/resend/",
        data=body, content_type="application/json",
        HTTP_SVIX_SIGNATURE=_sign(body, configured_webhook),
    )
    assert resp.status_code == 200
    delivered_delivery.refresh_from_db()
    assert delivered_delivery.status == Delivery.STATUS_DELIVERED
    assert delivered_delivery.delivered_at is not None


@pytest.mark.django_db
def test_webhook_bounced_marks_subscriber_and_logs(configured_webhook, delivered_delivery):
    api = APIClient()
    event = {
        "type": "email.bounced",
        "data": {"email_id": "msg_test_123", "reason": "no such mailbox"},
    }
    body = json.dumps(event).encode("utf-8")
    resp = api.post(
        "/api/newsletter/webhooks/resend/",
        data=body, content_type="application/json",
        HTTP_SVIX_SIGNATURE=_sign(body, configured_webhook),
    )
    assert resp.status_code == 200
    delivered_delivery.refresh_from_db()
    assert delivered_delivery.status == Delivery.STATUS_BOUNCED
    sub = delivered_delivery.subscriber
    sub.refresh_from_db()
    assert sub.status == Subscriber.STATUS_BOUNCED
    assert BounceEvent.objects.filter(
        subscriber=sub, kind=BounceEvent.KIND_HARD,
    ).exists()


@pytest.mark.django_db
def test_webhook_complaint_marks_subscriber(configured_webhook, delivered_delivery):
    api = APIClient()
    event = {
        "type": "email.complained",
        "data": {"email_id": "msg_test_123"},
    }
    body = json.dumps(event).encode("utf-8")
    resp = api.post(
        "/api/newsletter/webhooks/resend/",
        data=body, content_type="application/json",
        HTTP_SVIX_SIGNATURE=_sign(body, configured_webhook),
    )
    assert resp.status_code == 200
    delivered_delivery.subscriber.refresh_from_db()
    assert delivered_delivery.subscriber.status == Subscriber.STATUS_COMPLAINED
