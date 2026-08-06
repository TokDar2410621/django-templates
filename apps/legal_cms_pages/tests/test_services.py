"""Service-layer tests for legal_cms_pages."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from legal_cms_pages.models import LegalDocument
from legal_cms_pages.services import get_active, publish_document, render_html


def test_render_html_sanitizes_scripts():
    out = render_html("Hello <script>alert(1)</script> **world**")
    assert "<script>" not in out
    assert "<strong>world</strong>" in out


def test_render_html_supports_tables():
    md = "| a | b |\n|---|---|\n| 1 | 2 |\n"
    out = render_html(md)
    assert "<table>" in out
    assert "<td>1</td>" in out


@pytest.mark.django_db
def test_publish_document_deactivates_previous(user):
    old = publish_document(
        kind="terms_of_service",
        language="fr",
        title="CGU v1",
        body_markdown="v1",
        effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        created_by=user,
    )
    new = publish_document(
        kind="terms_of_service",
        language="fr",
        title="CGU v2",
        body_markdown="v2",
        effective_from=datetime(2026, 2, 1, tzinfo=timezone.utc),
        created_by=user,
    )
    old.refresh_from_db()
    assert old.is_active is False
    assert new.is_active is True
    # Active = exactly one row
    assert LegalDocument.objects.filter(
        kind="terms_of_service", language="fr", is_active=True,
    ).count() == 1


@pytest.mark.django_db
def test_get_active_falls_back_to_default_language(published_privacy_fr):
    # No EN version exists; service falls back to FR
    doc = get_active("privacy_policy", "en")
    assert doc is not None
    assert doc.language == "fr"


@pytest.mark.django_db
def test_get_active_returns_none_for_unpublished_kind():
    assert get_active("terms_of_service", "fr") is None
