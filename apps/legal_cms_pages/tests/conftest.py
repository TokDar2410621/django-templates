from __future__ import annotations

from datetime import datetime, timezone

import pytest
from django.contrib.auth import get_user_model

from legal_cms_pages.models import LegalDocument


@pytest.fixture
def user(db):
    User = get_user_model()
    return User.objects.create_user(
        username="legalop",
        email="legalop@example.com",
        password="pwpwpwpw",
    )


@pytest.fixture
def published_privacy_fr(db, user) -> LegalDocument:
    return LegalDocument.objects.create(
        kind="privacy_policy",
        language="fr",
        title="Politique de confidentialité",
        body_markdown="## Bonjour\n\nVoici notre politique.",
        effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        is_active=True,
        created_by=user,
    )
