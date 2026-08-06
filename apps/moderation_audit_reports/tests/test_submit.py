"""Tests for ``submit_report`` — creates a Report + a ModerationLog row."""
from __future__ import annotations

import pytest

from moderation_audit_reports.models import (
    ModerationLog,
    Report,
    ReportPriority,
    ReportReason,
)
from moderation_audit_reports.services import submit_report


@pytest.mark.django_db
def test_submit_report_creates_row_and_log(user, offender):
    report = submit_report(
        reporter=user,
        target_type="message",
        target_id="abc-123",
        target_owner=offender,
        reason=ReportReason.HARASSMENT,
        description="this person keeps spamming me",
    )
    assert report.pk is not None
    assert report.reporter == user
    assert report.target_owner == offender
    assert report.target_type == "message"
    assert report.target_id == "abc-123"
    assert report.priority == ReportPriority.MEDIUM  # harassment reason
    assert report.status == "open"

    log = ModerationLog.objects.filter(
        action="report.submit", target_id="abc-123",
    ).first()
    assert log is not None
    assert log.actor == user


@pytest.mark.django_db
def test_submit_report_with_urgent_description(user, offender):
    report = submit_report(
        reporter=user,
        target_type="post",
        target_id="post-7",
        target_owner=offender,
        reason=ReportReason.OTHER,
        description="he posted a threat to kill someone",
    )
    assert report.priority == ReportPriority.URGENT


@pytest.mark.django_db
def test_submit_report_coerces_target_id_to_string(user, offender):
    report = submit_report(
        reporter=user,
        target_type="post",
        target_id=42,  # int — should be coerced
        target_owner=offender,
        reason=ReportReason.SPAM,
    )
    assert report.target_id == "42"


@pytest.mark.django_db
def test_submit_report_anonymous_reporter(db, offender):
    # Pass an AnonymousUser-like (not authenticated) — should store None
    class _Anon:
        is_authenticated = False
        pk = None

    report = submit_report(
        reporter=_Anon(),
        target_type="message",
        target_id="anon-1",
        target_owner=offender,
        reason=ReportReason.SPAM,
    )
    assert report.reporter is None


@pytest.mark.django_db
def test_submit_report_prefix_namespaced_target_id(user, offender):
    """SMN-style prefix-namespaced ids (``conv_msg:<uuid>``) must round-trip."""
    report = submit_report(
        reporter=user,
        target_type="message",
        target_id="conv_msg:550e8400-e29b-41d4-a716-446655440000",
        target_owner=offender,
        reason=ReportReason.OTHER,
    )
    assert report.target_id.startswith("conv_msg:")
    assert Report.objects.filter(target_id__startswith="conv_msg:").exists()
