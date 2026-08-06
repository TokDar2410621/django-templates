"""Token revocation tests."""
from __future__ import annotations

import pytest

from hashed_api_tokens.models import ApiToken
from hashed_api_tokens.services import create_token, revoke_token


@pytest.mark.django_db
def test_owner_can_revoke_own_token(user):
    token, _ = create_token(user, "ci")
    result = revoke_token(token.pk, user)
    assert result is not None
    assert result.revoked_at is not None
    assert result.is_active is False


@pytest.mark.django_db
def test_user_cannot_revoke_others_token(user, other_user):
    token, _ = create_token(user, "ci")
    result = revoke_token(token.pk, other_user)
    assert result is None
    token.refresh_from_db()
    assert token.revoked_at is None


@pytest.mark.django_db
def test_staff_can_revoke_anyone(user, other_user):
    other_user.is_staff = True
    other_user.save(update_fields=["is_staff"])
    token, _ = create_token(user, "ci")
    result = revoke_token(token.pk, other_user)
    assert result is not None
    assert result.revoked_at is not None


@pytest.mark.django_db
def test_revoke_is_idempotent(user):
    token, _ = create_token(user, "ci")
    first = revoke_token(token.pk, user)
    revoked_at_first = first.revoked_at
    second = revoke_token(token.pk, user)
    # Same row returned, timestamp unchanged.
    assert second is not None
    assert second.revoked_at == revoked_at_first


@pytest.mark.django_db
def test_revoke_returns_none_for_missing_id(user):
    assert revoke_token(99999, user) is None


@pytest.mark.django_db
def test_revoke_endpoint(api, user):
    token, _ = create_token(user, "ci")
    api.force_authenticate(user)
    resp = api.post(f"/api/tokens/{token.pk}/revoke/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["revoked_at"] is not None
    assert body["is_active"] is False


@pytest.mark.django_db
def test_revoke_endpoint_blocks_other_user(api, user, other_user):
    token, _ = create_token(user, "ci")
    api.force_authenticate(other_user)
    resp = api.post(f"/api/tokens/{token.pk}/revoke/")
    assert resp.status_code == 404
    token.refresh_from_db()
    assert token.revoked_at is None


@pytest.mark.django_db
def test_revoke_endpoint_requires_auth(api, user):
    token, _ = create_token(user, "ci")
    resp = api.post(f"/api/tokens/{token.pk}/revoke/")
    assert resp.status_code in (401, 403)


@pytest.mark.django_db
def test_list_excludes_revoked_by_default(api, user):
    t1, _ = create_token(user, "live")
    t2, _ = create_token(user, "old")
    revoke_token(t2.pk, user)
    api.force_authenticate(user)
    resp = api.get("/api/tokens/")
    ids = {row["id"] for row in resp.json()["results"]}
    assert t1.pk in ids
    assert t2.pk not in ids


@pytest.mark.django_db
def test_list_can_include_revoked(api, user):
    t1, _ = create_token(user, "live")
    t2, _ = create_token(user, "old")
    revoke_token(t2.pk, user)
    api.force_authenticate(user)
    resp = api.get("/api/tokens/?include_revoked=1")
    ids = {row["id"] for row in resp.json()["results"]}
    assert {t1.pk, t2.pk} <= ids
