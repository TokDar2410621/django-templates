"""API tests for legal_cms_pages."""
from __future__ import annotations

import pytest
from rest_framework.test import APIClient


@pytest.fixture
def api() -> APIClient:
    return APIClient()


@pytest.mark.django_db
def test_index_returns_active_documents(api, published_privacy_fr):
    resp = api.get("/api/legal/?lang=fr")
    assert resp.status_code == 200
    body = resp.json()
    assert any(doc["kind"] == "privacy_policy" for doc in body)


@pytest.mark.django_db
def test_detail_returns_body_html(api, published_privacy_fr):
    resp = api.get("/api/legal/privacy_policy/?lang=fr")
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "privacy_policy"
    assert "<h2>Bonjour</h2>" in body["body_html"]


@pytest.mark.django_db
def test_detail_404_when_unpublished(api):
    resp = api.get("/api/legal/terms_of_service/?lang=fr")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_detail_falls_back_to_default_language(api, published_privacy_fr):
    # Request EN — only FR is published; service falls back
    resp = api.get("/api/legal/privacy_policy/?lang=en")
    assert resp.status_code == 200
    body = resp.json()
    assert body["language"] == "fr"
