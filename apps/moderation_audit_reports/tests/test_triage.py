"""Tests for ``triage_report`` — updates status + writes ModerationLog."""
from __future__ import annotations

import pytest

from moderation_audit_reports.models import ModerationLog, Report, ReportStatus
from moderation_audit_reports.services import triage_report


@pytest.mark.django_db
def test_triage_to_actioned_sets_actioned_by_and_at(staff, existing_report):
    triage_report(
        report=existing_report,
        actor=staff,
        status=ReportStatus.ACTIONED,
        note="confirmed violation",
    )
    existing_report.refresh_from_db()
    assert existing_report.status == ReportStatus.ACTIONED
    assert existing_report.actioned_by == staff
    assert existing_report.actioned_at is not None


@pytest.mark.django_db
def test_triage_writes_log_with_before_after(staff, existing_report):
    triage_report(
        report=existing_report,
        actor=staff,
        status=ReportStatus.DISMISSED,
        note="not a violation, just rude",
    )
    log = ModerationLog.objects.filter(
        action="report.dismissed", target_id=str(existing_report.pk),
    ).first()
    assert log is not None
    assert log.actor == staff
    assert log.before == {"status": "open", "priority": 0}
    assert log.after == {"status": "dismissed", "priority": 0}
    assert log.note == "not a violation, just rude"


@pytest.mark.django_db
def test_triage_to_triaged_does_not_set_actioned(staff, existing_report):
    triage_report(
        report=existing_report,
        actor=staff,
        status=ReportStatus.TRIAGED,
        note="needs more info",
    )
    existing_report.refresh_from_db()
    assert existing_report.status == ReportStatus.TRIAGED
    assert existing_report.actioned_by is None
    assert existing_report.actioned_at is None


@pytest.mark.django_db
def test_triage_invalid_status_raises(staff, existing_report):
    with pytest.raises(ValueError):
        triage_report(
            report=existing_report,
            actor=staff,
            status="nonexistent_status",
        )
