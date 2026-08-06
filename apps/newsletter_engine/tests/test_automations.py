"""Automation enrollment + tick tests."""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from newsletter_engine.backends.dummy import DummyBackend
from newsletter_engine.models import AutomationEnrollment, AutomationStep
from newsletter_engine.services.automations import (
    enroll_subscriber,
    handle_trigger,
    process_due_enrollments,
    tick_automation,
)


@pytest.mark.django_db
def test_enroll_creates_active_enrollment(confirmed_subscriber, manual_automation):
    enr = enroll_subscriber(manual_automation, confirmed_subscriber)
    assert enr.is_active
    assert enr.last_step_index == -1


@pytest.mark.django_db
def test_enroll_twice_returns_same_active(confirmed_subscriber, manual_automation):
    e1 = enroll_subscriber(manual_automation, confirmed_subscriber)
    e2 = enroll_subscriber(manual_automation, confirmed_subscriber)
    assert e1.pk == e2.pk


@pytest.mark.django_db
def test_first_step_fires_immediately(confirmed_subscriber, manual_automation):
    enr = enroll_subscriber(manual_automation, confirmed_subscriber)
    step = tick_automation(enr)
    assert step is not None
    assert step.order == 0
    enr.refresh_from_db()
    assert enr.last_step_index == 0
    # Email should have hit the dummy backend.
    assert any(e["to"] == confirmed_subscriber.email for e in DummyBackend.outbox)


@pytest.mark.django_db
def test_second_step_blocked_by_delay(confirmed_subscriber, manual_automation):
    enr = enroll_subscriber(manual_automation, confirmed_subscriber)
    tick_automation(enr)
    enr.refresh_from_db()
    # Step 1 has 60s delay; trying to tick again right away should be None.
    next_step = tick_automation(enr)
    assert next_step is None


@pytest.mark.django_db
def test_second_step_fires_after_delay(confirmed_subscriber, manual_automation):
    enr = enroll_subscriber(manual_automation, confirmed_subscriber)
    tick_automation(enr)
    enr.refresh_from_db()
    future = timezone.now() + timedelta(seconds=120)
    step = tick_automation(enr, now=future)
    assert step is not None
    assert step.order == 1


@pytest.mark.django_db
def test_condition_skips_step_but_advances_index(
    confirmed_subscriber, manual_automation,
):
    """Step 1 with a condition that doesn't match should be skipped (no email),
    but the index should still advance so we don't loop.
    """
    step1 = AutomationStep.objects.get(automation=manual_automation, order=1)
    step1.condition = {
        "op": "field", "field": "locale", "compare": "eq", "value": "zz-impossible",
    }
    step1.save()

    enr = enroll_subscriber(manual_automation, confirmed_subscriber)
    tick_automation(enr)
    DummyBackend.reset()
    future = timezone.now() + timedelta(seconds=120)
    tick_automation(enr, now=future)
    enr.refresh_from_db()
    # Index advanced...
    assert enr.last_step_index == 1
    # ...but no email was sent.
    assert DummyBackend.outbox == []


@pytest.mark.django_db
def test_unsendable_subscriber_no_email(tenant, manual_automation):
    """Bounced subscriber: enrolling them is allowed, but the step delivery
    silently skips the send.
    """
    from newsletter_engine.models import Subscriber
    sub = Subscriber.objects.create(
        tenant=tenant, email="dead@example.com",
        status=Subscriber.STATUS_BOUNCED,
    )
    enr = enroll_subscriber(manual_automation, sub)
    tick_automation(enr)
    assert DummyBackend.outbox == []


@pytest.mark.django_db
def test_completion_after_last_step(confirmed_subscriber, manual_automation):
    enr = enroll_subscriber(manual_automation, confirmed_subscriber)
    tick_automation(enr)
    enr.refresh_from_db()
    future = timezone.now() + timedelta(seconds=120)
    tick_automation(enr, now=future)
    enr.refresh_from_db()
    # No more steps — next tick completes.
    tick_automation(enr, now=future + timedelta(seconds=120))
    enr.refresh_from_db()
    assert enr.completed_at is not None


@pytest.mark.django_db
def test_cancelled_enrollment_is_skipped(confirmed_subscriber, manual_automation):
    enr = enroll_subscriber(manual_automation, confirmed_subscriber)
    enr.cancelled_at = timezone.now()
    enr.cancellation_reason = "user request"
    enr.save()
    step = tick_automation(enr)
    assert step is None


@pytest.mark.django_db
def test_handle_trigger_enrolls_matching_automation(
    confirmed_subscriber, manual_automation, tenant,
):
    """Trigger 'manual' with empty config matches every manual automation."""
    enrollments = handle_trigger(
        tenant=tenant, trigger="manual", subscriber=confirmed_subscriber,
    )
    assert any(e.automation_id == manual_automation.pk for e in enrollments)


@pytest.mark.django_db
def test_handle_trigger_filters_by_config(tenant, confirmed_subscriber):
    """An automation with trigger_config={"list_id":99} fires only for that list."""
    from newsletter_engine.models import Automation, AutomationStep
    auto = Automation.objects.create(
        tenant=tenant, name="welcome to list 99",
        trigger="list_joined", trigger_config={"list_id": 99}, is_active=True,
    )
    AutomationStep.objects.create(
        automation=auto, order=0, delay_seconds=0,
        subject="welcome", html_body="<p>welcome</p>",
    )
    # Wrong list_id — should not enroll.
    enrollments = handle_trigger(
        tenant=tenant, trigger="list_joined",
        subscriber=confirmed_subscriber, context={"list_id": 1},
    )
    assert enrollments == []
    # Right list_id — should enroll.
    enrollments = handle_trigger(
        tenant=tenant, trigger="list_joined",
        subscriber=confirmed_subscriber, context={"list_id": 99},
    )
    assert len(enrollments) == 1


@pytest.mark.django_db
def test_process_due_enrollments_advances_multiple(
    tenant, manual_automation,
):
    """End-to-end: several enrollments are ticked in one process_due call."""
    from newsletter_engine.models import Subscriber
    subs = [
        Subscriber.objects.create(
            tenant=tenant, email=f"u{i}@example.com",
            status=Subscriber.STATUS_CONFIRMED,
        )
        for i in range(3)
    ]
    for s in subs:
        enroll_subscriber(manual_automation, s)
    n = process_due_enrollments()
    assert n == 3
