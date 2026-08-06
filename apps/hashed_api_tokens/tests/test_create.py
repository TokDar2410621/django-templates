"""Token creation tests."""
from __future__ import annotations

import hashlib

import pytest

from hashed_api_tokens.models import ApiToken
from hashed_api_tokens.services import (
    create_token,
    generate_plain_token,
    get_token_prefix,
    hash_token,
)


@pytest.mark.django_db
def test_create_token_returns_plain_token(user):
    token, plain = create_token(user, "n8n production")
    assert plain.startswith(f"{get_token_prefix()}_")
    assert token.user == user
    assert token.name == "n8n production"
    assert token.key_prefix == plain[:12]
    assert token.revoked_at is None
    assert token.is_active is True


@pytest.mark.django_db
def test_plain_token_is_not_persisted(user):
    """The DB must contain ONLY the hash — not the plain token, anywhere."""
    _, plain = create_token(user, "ci-runner")
    # The plain token must not appear in any text-ish column of the row.
    row = ApiToken.objects.values().get(user=user)
    for field, value in row.items():
        if not isinstance(value, str):
            continue
        assert plain not in value, f"plain token leaked into field {field}"


@pytest.mark.django_db
def test_hash_is_sha256_of_plain(user):
    _, plain = create_token(user, "zapier")
    expected = hashlib.sha256(plain.encode("utf-8")).hexdigest()
    assert ApiToken.objects.get(user=user).key_hash == expected
    assert hash_token(plain) == expected


@pytest.mark.django_db
def test_create_token_rejects_empty_name(user):
    with pytest.raises(ValueError):
        create_token(user, "   ")


@pytest.mark.django_db
def test_create_token_truncates_long_name(user):
    long_name = "x" * 250
    token, _ = create_token(user, long_name)
    assert len(token.name) == 100


@pytest.mark.django_db
def test_multiple_tokens_per_user(user):
    """A user can hold many tokens (one per integration)."""
    _, p1 = create_token(user, "n8n")
    _, p2 = create_token(user, "zapier")
    assert p1 != p2
    assert ApiToken.objects.filter(user=user).count() == 2


def test_generate_plain_token_uses_configured_prefix(settings):
    settings.API_TOKEN_PREFIX = "myapp"
    plain, h, prefix = generate_plain_token()
    assert plain.startswith("myapp_")
    assert prefix == plain[:12]
    assert h == hashlib.sha256(plain.encode("utf-8")).hexdigest()


@pytest.mark.django_db
def test_create_endpoint_returns_plain_once(api, user):
    api.force_authenticate(user)
    resp = api.post("/api/tokens/", {"name": "Zapier prod"}, format="json")
    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert "token" in body
    assert body["token"].startswith(f"{get_token_prefix()}_")
    assert body["name"] == "Zapier prod"
    assert "message" in body

    # Subsequent GET must NOT contain the plain token anywhere.
    resp2 = api.get("/api/tokens/")
    assert resp2.status_code == 200
    assert body["token"] not in resp2.content.decode("utf-8")


@pytest.mark.django_db
def test_create_endpoint_rejects_blank_name(api, user):
    api.force_authenticate(user)
    resp = api.post("/api/tokens/", {"name": "   "}, format="json")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_create_endpoint_requires_auth(api):
    resp = api.post("/api/tokens/", {"name": "Zapier"}, format="json")
    assert resp.status_code in (401, 403)
