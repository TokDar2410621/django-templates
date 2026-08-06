from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from moderation_audit_reports.models import Report, ReportReason


@pytest.fixture
def user(db):
    User = get_user_model()
    return User.objects.create_user(
        username="reporter1",
        email="reporter1@example.com",
        password="pwpwpwpw",
    )


@pytest.fixture
def offender(db):
    User = get_user_model()
    return User.objects.create_user(
        username="offender1",
        email="offender1@example.com",
        password="pwpwpwpw",
    )


@pytest.fixture
def staff(db):
    User = get_user_model()
    return User.objects.create_user(
        username="mod1",
        email="mod1@example.com",
        password="pwpwpwpw",
        is_staff=True,
    )


@pytest.fixture
def existing_report(db, user, offender) -> Report:
    return Report.objects.create(
        reporter=user,
        target_type="message",
        target_id="msg-123",
        target_owner=offender,
        reason=ReportReason.OTHER,
        description="boring",
        priority=0,
    )
