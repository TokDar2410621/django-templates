"""HashedTokenAuthentication tests — valid, revoked, wrong, X-Api-Key."""
from __future__ import annotations

import pytest
from django.urls import path
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.test import APIClient, URLPatternsTestCase
from rest_framework.views import APIView

from hashed_api_tokens.authentication import HashedTokenAuthentication
from hashed_api_tokens.models import ApiToken
from hashed_api_tokens.services import create_token, revoke_token


# ---------------------------------------------------------------------------
# A throwaway view to authenticate against. We can't rely on the project
# having any token-authenticated endpoint, so we declare one inline.
# ---------------------------------------------------------------------------

class _ProbeView(APIView):
    authentication_classes = [HashedTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            "user_id": request.user.pk,
            "token_name": getattr(request.auth, "name", None),
        })


@pytest.fixture
def probe_urls(settings):
    """Add a temporary /__probe__/ URL for the duration of the test."""
    # Build a fresh urlconf module on the fly.
    import types
    module = types.ModuleType("hashed_api_tokens_probe_urls")
    module.urlpatterns = [
        path("__probe__/", _ProbeView.as_view(), name="probe"),
    ]
    import sys
    sys.modules["hashed_api_tokens_probe_urls"] = module
    settings.ROOT_URLCONF = "hashed_api_tokens_probe_urls"
    yield
    sys.modules.pop("hashed_api_tokens_probe_urls", None)


@pytest.mark.django_db
def test_valid_token_authenticates_via_bearer(probe_urls, api, user):
    _, plain = create_token(user, "ci")
    resp = api.get("/__probe__/", HTTP_AUTHORIZATION=f"Bearer {plain}")
    assert resp.status_code == 200, resp.content
    assert resp.json()["user_id"] == user.pk
    assert resp.json()["token_name"] == "ci"


@pytest.mark.django_db
def test_valid_token_authenticates_via_x_api_key(probe_urls, api, user):
    _, plain = create_token(user, "n8n")
    resp = api.get("/__probe__/", HTTP_X_API_KEY=plain)
    assert resp.status_code == 200
    assert resp.json()["user_id"] == user.pk


@pytest.mark.django_db
def test_revoked_token_is_rejected(probe_urls, api, user):
    token, plain = create_token(user, "old-ci")
    revoke_token(token.pk, user)
    resp = api.get("/__probe__/", HTTP_AUTHORIZATION=f"Bearer {plain}")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_unknown_token_is_rejected(probe_urls, api):
    resp = api.get("/__probe__/", HTTP_AUTHORIZATION="Bearer tkn_doesnotexist")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_garbage_format_is_rejected(probe_urls, api, settings):
    settings.API_TOKEN_PREFIX = "tkn"
    resp = api.get("/__probe__/", HTTP_AUTHORIZATION="Bearer otherapp_abc123")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_missing_header_is_unauthenticated(probe_urls, api):
    resp = api.get("/__probe__/")
    # No auth header at all → IsAuthenticated fails with 401.
    assert resp.status_code == 401


@pytest.mark.django_db
def test_last_used_at_is_updated(probe_urls, api, user):
    token, plain = create_token(user, "ci")
    assert token.last_used_at is None
    api.get("/__probe__/", HTTP_AUTHORIZATION=f"Bearer {plain}")
    token.refresh_from_db()
    assert token.last_used_at is not None


@pytest.mark.django_db
def test_last_used_update_is_rate_limited(probe_urls, api, user):
    """Two rapid requests should NOT trigger two DB writes (within 1 min)."""
    from django.utils import timezone
    from datetime import timedelta

    token, plain = create_token(user, "ci")
    # Seed last_used_at as 5 seconds ago.
    recent = timezone.now() - timedelta(seconds=5)
    ApiToken.objects.filter(pk=token.pk).update(last_used_at=recent)
    api.get("/__probe__/", HTTP_AUTHORIZATION=f"Bearer {plain}")
    token.refresh_from_db()
    # Within the 1-minute window → still equals the seeded value.
    assert abs((token.last_used_at - recent).total_seconds()) < 1
