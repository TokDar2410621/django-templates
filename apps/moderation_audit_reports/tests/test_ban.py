"""Tests for ``ban_user`` / ``unban_user`` / ``is_banned``."""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from moderation_audit_reports.models import BannedUser, ModerationLog
from moderation_audit_reports.selectors import is_banned
from moderation_audit_reports.services import ban_user, unban_user


@pytest.mark.django_db
def test_ban_user_creates_record_and_log(staff, offender):
    ban = ban_user(user=offender, by=staff, reason="spam")
    assert ban.user == offender
    assert ban.banned_by == staff
    assert ban.banned_until is None  # permanent

    log = ModerationLog.objects.filter(
        action="user.ban", target_id=str(offender.pk),
    ).first()
    assert log is not None
    assert log.actor == staff


@pytest.mark.django_db
def test_ban_user_is_idempotent(staff, offender):
    ban_user(user=offender, by=staff, reason="first")
    ban_user(user=offender, by=staff, reason="second")
    assert BannedUser.objects.filter(user=offender).count() == 1
    refreshed = BannedUser.objects.get(user=offender)
    assert refreshed.reason == "second"  # update_or_create overwrote


@pytest.mark.django_db
def test_ban_user_with_days_sets_banned_until(staff, offender):
    ban = ban_user(user=offender, by=staff, reason="7-day", days=7)
    assert ban.banned_until is not None
    delta = ban.banned_until - timezone.now()
    # ±2-minute slack to account for fixture creation latency
    assert timedelta(days=6, hours=23, minutes=58) <= delta <= timedelta(days=7, minutes=2)


@pytest.mark.django_db
def test_unban_user_removes_record_and_logs(staff, offender):
    ban_user(user=offender, by=staff, reason="will be lifted")
    assert BannedUser.objects.filter(user=offender).exists()

    unban_user(user=offender, by=staff, note="appeal accepted")
    assert not BannedUser.objects.filter(user=offender).exists()

    log = ModerationLog.objects.filter(
        action="user.unban", target_id=str(offender.pk),
    ).first()
    assert log is not None
    assert log.actor == staff
    assert log.note == "appeal accepted"


@pytest.mark.django_db
def test_is_banned_permanent(staff, offender):
    ban_user(user=offender, by=staff, reason="permanent")
    assert is_banned(offender) is True


@pytest.mark.django_db
def test_is_banned_expired_returns_false(staff, offender):
    ban = ban_user(user=offender, by=staff, reason="expired", days=1)
    # Force the banned_until into the past
    ban.banned_until = timezone.now() - timedelta(hours=1)
    ban.save(update_fields=["banned_until"])
    assert is_banned(offender) is False


@pytest.mark.django_db
def test_is_banned_future_returns_true(staff, offender):
    ban_user(user=offender, by=staff, reason="not yet expired", days=30)
    assert is_banned(offender) is True


@pytest.mark.django_db
def test_is_banned_no_record_returns_false(offender):
    assert is_banned(offender) is False


@pytest.mark.django_db
def test_is_banned_none_user_returns_false():
    assert is_banned(None) is False
