"""Push subscribe/unsubscribe — service-level + HTTP-level coverage."""
from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from notifications_multichannel.models import PushSubscription
from notifications_multichannel.services import subscribe_push, unsubscribe_push


# ---------------------------------------------------------------------------
# Service layer
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_subscribe_push_is_idempotent_per_endpoint(user):
    sub1 = subscribe_push(
        user=user, endpoint="https://example.com/a",
        p256dh="k1", auth="a1",
    )
    sub2 = subscribe_push(
        user=user, endpoint="https://example.com/a",
        p256dh="k2", auth="a2",
    )
    assert sub1.pk == sub2.pk
    assert PushSubscription.objects.filter(user=user).count() == 1
    sub2.refresh_from_db()
    assert sub2.p256dh == "k2"


@pytest.mark.django_db
def test_unsubscribe_push_deletes_only_user_endpoint(user, db):
    from django.contrib.auth import get_user_model
    other = get_user_model().objects.create_user(
        username="other", email="other@example.com", password="pw",
    )
    PushSubscription.objects.create(
        user=user, endpoint="https://example.com/a",
        p256dh="k", auth="a",
    )
    PushSubscription.objects.create(
        user=other, endpoint="https://example.com/a-other",
        p256dh="k", auth="a",
    )
    n = unsubscribe_push(user=user, endpoint="https://example.com/a")
    assert n == 1
    assert PushSubscription.objects.filter(user=other).count() == 1


# ---------------------------------------------------------------------------
# HTTP layer — requires URLs wired in the test project at /api/notifications/
# Tests are kept tolerant to URL prefix by using reverse().
# ---------------------------------------------------------------------------
@pytest.fixture
def api() -> APIClient:
    return APIClient()


@pytest.mark.django_db
def test_subscribe_view_requires_auth(api):
    resp = api.post(
        "/api/notifications/push/subscribe/",
        data={"endpoint": "https://e", "keys": {"p256dh": "k", "auth": "a"}},
        format="json",
    )
    assert resp.status_code in (401, 403)


@pytest.mark.django_db
def test_subscribe_view_validates_payload(api, user):
    api.force_authenticate(user=user)
    resp = api.post(
        "/api/notifications/push/subscribe/",
        data={"endpoint": "https://example.com/a", "keys": {"p256dh": "k"}},
        format="json",
    )
    # Missing auth key → 400 from serializer
    assert resp.status_code == 400


@pytest.mark.django_db
def test_subscribe_view_creates_row(api, user):
    api.force_authenticate(user=user)
    resp = api.post(
        "/api/notifications/push/subscribe/",
        data={
            "endpoint": "https://example.com/a",
            "keys": {"p256dh": "k", "auth": "a"},
        },
        format="json",
    )
    assert resp.status_code == 201
    assert PushSubscription.objects.filter(user=user).count() == 1


@pytest.mark.django_db
def test_unsubscribe_view_deletes(api, user):
    PushSubscription.objects.create(
        user=user, endpoint="https://example.com/a",
        p256dh="k", auth="a",
    )
    api.force_authenticate(user=user)
    resp = api.post(
        "/api/notifications/push/unsubscribe/",
        data={"endpoint": "https://example.com/a"},
        format="json",
    )
    assert resp.status_code == 204
    assert PushSubscription.objects.filter(user=user).count() == 0
