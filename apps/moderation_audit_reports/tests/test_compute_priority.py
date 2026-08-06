"""Unit tests for the pure ``compute_priority`` function.

These run without touching the DB except for the repeat-report
escalation test (which needs ``Report.objects.filter(...).count()``).
"""
from __future__ import annotations

import pytest

from moderation_audit_reports.models import (
    Report,
    ReportPriority,
    ReportReason,
    ReportStatus,
)
from moderation_audit_reports.services import compute_priority


# --- reason-based ----------------------------------------------------------
@pytest.mark.django_db
def test_threat_reason_is_urgent():
    p = compute_priority(
        target_type="message", target_id="t1",
        reason=ReportReason.THREAT, description="",
    )
    assert p == ReportPriority.URGENT


@pytest.mark.django_db
def test_minor_reason_is_urgent():
    p = compute_priority(
        target_type="message", target_id="t1",
        reason=ReportReason.MINOR, description="",
    )
    assert p == ReportPriority.URGENT


@pytest.mark.django_db
def test_hate_reason_is_high():
    p = compute_priority(
        target_type="message", target_id="t1",
        reason=ReportReason.HATE, description="",
    )
    assert p == ReportPriority.HIGH


@pytest.mark.django_db
def test_illegal_reason_is_high():
    p = compute_priority(
        target_type="message", target_id="t1",
        reason=ReportReason.ILLEGAL, description="",
    )
    assert p == ReportPriority.HIGH


@pytest.mark.django_db
def test_harassment_reason_is_medium():
    p = compute_priority(
        target_type="message", target_id="t1",
        reason=ReportReason.HARASSMENT, description="",
    )
    assert p == ReportPriority.MEDIUM


@pytest.mark.django_db
def test_spam_reason_is_low():
    p = compute_priority(
        target_type="message", target_id="t1",
        reason=ReportReason.SPAM, description="",
    )
    assert p == ReportPriority.LOW


@pytest.mark.django_db
def test_other_reason_is_low_by_default():
    p = compute_priority(
        target_type="message", target_id="t1",
        reason=ReportReason.OTHER, description="boring",
    )
    assert p == ReportPriority.LOW


# --- keyword-based ---------------------------------------------------------
@pytest.mark.django_db
def test_urgent_keyword_french_promotes_to_urgent():
    p = compute_priority(
        target_type="post", target_id="p42",
        reason=ReportReason.OTHER,
        description="il me menace de me tuer",
    )
    assert p == ReportPriority.URGENT


@pytest.mark.django_db
def test_urgent_keyword_english_promotes_to_urgent():
    p = compute_priority(
        target_type="post", target_id="p42",
        reason=ReportReason.OTHER,
        description="he said he would kill me",
    )
    assert p == ReportPriority.URGENT


@pytest.mark.django_db
def test_high_keyword_promotes_to_high():
    p = compute_priority(
        target_type="post", target_id="p42",
        reason=ReportReason.OTHER,
        description="this is harassment from a stalker",
    )
    assert p == ReportPriority.HIGH


@pytest.mark.django_db
def test_minor_keyword_promotes_to_urgent():
    p = compute_priority(
        target_type="post", target_id="p42",
        reason=ReportReason.OTHER,
        description="explicit child content posted",
    )
    assert p == ReportPriority.URGENT


# --- repeat-report escalation ----------------------------------------------
@pytest.mark.django_db
def test_repeat_reports_escalate_one_step(offender):
    # Two prior OPEN reports already exist for the same target
    for i in range(2):
        Report.objects.create(
            target_type="message", target_id="hot-msg",
            reason=ReportReason.OTHER, description="",
            priority=int(ReportPriority.LOW),
            status=ReportStatus.OPEN,
            target_owner=offender,
        )
    # Default threshold = 3. The next report (this would be the 3rd) should
    # bump LOW → MEDIUM.
    p = compute_priority(
        target_type="message", target_id="hot-msg",
        reason=ReportReason.OTHER, description="",
    )
    assert p == ReportPriority.MEDIUM


@pytest.mark.django_db
def test_repeat_escalation_caps_at_urgent(offender):
    # Five prior HIGH-priority OPEN reports
    for i in range(5):
        Report.objects.create(
            target_type="message", target_id="really-hot",
            reason=ReportReason.HATE, description="",
            priority=int(ReportPriority.HIGH),
            status=ReportStatus.OPEN,
            target_owner=offender,
        )
    # New report should land URGENT (HIGH + 1 step, capped)
    p = compute_priority(
        target_type="message", target_id="really-hot",
        reason=ReportReason.HATE, description="",
    )
    assert p == ReportPriority.URGENT


@pytest.mark.django_db
def test_repeat_escalation_does_not_count_closed_reports(offender):
    # Two prior reports BUT actioned/dismissed — should not escalate
    for status_ in ("actioned", "dismissed"):
        Report.objects.create(
            target_type="message", target_id="cold-msg",
            reason=ReportReason.OTHER, description="",
            priority=int(ReportPriority.LOW),
            status=status_,
            target_owner=offender,
        )
    p = compute_priority(
        target_type="message", target_id="cold-msg",
        reason=ReportReason.OTHER, description="",
    )
    assert p == ReportPriority.LOW  # no escalation, all priors are closed
