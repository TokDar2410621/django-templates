"""Campaign creation, sending (with DummyBackend), stats, cancel."""
from __future__ import annotations

import pytest

from newsletter_engine.backends.dummy import DummyBackend
from newsletter_engine.exceptions import CampaignStateError
from newsletter_engine.models import (
    Campaign,
    Delivery,
    Membership,
)
from newsletter_engine.services.campaigns import (
    cancel_campaign,
    compute_campaign_stats,
    create_campaign,
    fan_out,
    send_campaign,
)
from newsletter_engine.services.subscribers import add_to_list


@pytest.fixture
def list_with_subs(tenant, mailing_list, db):
    """A list with two confirmed subscribers added to it."""
    from newsletter_engine.models import Subscriber
    s1 = Subscriber.objects.create(
        tenant=tenant, email="s1@example.com",
        status=Subscriber.STATUS_CONFIRMED,
    )
    s2 = Subscriber.objects.create(
        tenant=tenant, email="s2@example.com",
        status=Subscriber.STATUS_CONFIRMED,
    )
    s3_bounced = Subscriber.objects.create(
        tenant=tenant, email="s3@example.com",
        status=Subscriber.STATUS_BOUNCED,
    )
    for s in (s1, s2, s3_bounced):
        add_to_list(s, mailing_list)
    return mailing_list, [s1, s2, s3_bounced]


@pytest.mark.django_db
def test_create_campaign_draft_by_default(tenant, mailing_list):
    camp = create_campaign(
        tenant=tenant, target=mailing_list,
        subject="Hi", html_body="<p>Hi</p>",
    )
    assert camp.status == Campaign.STATUS_DRAFT
    assert camp.list_id == mailing_list.pk
    assert camp.segment_id is None


@pytest.mark.django_db
def test_create_campaign_scheduled(tenant, mailing_list):
    from django.utils import timezone
    when = timezone.now()
    camp = create_campaign(
        tenant=tenant, target=mailing_list,
        subject="Hi", html_body="<p>Hi</p>",
        scheduled_at=when,
    )
    assert camp.status == Campaign.STATUS_SCHEDULED
    assert camp.scheduled_at is not None


@pytest.mark.django_db
def test_create_campaign_with_segment_target(tenant, empty_segment):
    camp = create_campaign(
        tenant=tenant, target=empty_segment,
        subject="Hi", html_body="<p>Hi</p>",
    )
    assert camp.list_id is None
    assert camp.segment_id == empty_segment.pk


@pytest.mark.django_db
def test_fan_out_creates_deliveries_only_for_confirmed(list_with_subs, tenant):
    list_, subs = list_with_subs
    camp = create_campaign(
        tenant=tenant, target=list_,
        subject="Hi", html_body="<p>Hi</p>",
    )
    Campaign.objects.filter(pk=camp.pk).update(status=Campaign.STATUS_SENDING)
    camp.refresh_from_db()
    batches = fan_out(camp)
    # 2 confirmed subscribers; the bounced one is excluded.
    assert sum(len(b) for b in batches) == 2
    statuses = set(Delivery.objects.filter(campaign=camp).values_list("status", flat=True))
    assert statuses == {Delivery.STATUS_QUEUED}


@pytest.mark.django_db
def test_send_campaign_idempotent_on_sending(list_with_subs, tenant):
    """Calling send_campaign twice on a SENDING campaign is a no-op."""
    list_, _ = list_with_subs
    camp = create_campaign(
        tenant=tenant, target=list_,
        subject="Hi", html_body="<p>Hi</p>",
    )
    Campaign.objects.filter(pk=camp.pk).update(status=Campaign.STATUS_SENDING)
    camp.refresh_from_db()
    send_campaign(camp)  # should not raise


@pytest.mark.django_db
def test_send_campaign_refuses_sent_campaign(list_with_subs, tenant):
    list_, _ = list_with_subs
    camp = create_campaign(
        tenant=tenant, target=list_,
        subject="Hi", html_body="<p>Hi</p>",
    )
    Campaign.objects.filter(pk=camp.pk).update(status=Campaign.STATUS_SENT)
    camp.refresh_from_db()
    # SENT is the success state, so it's a no-op rather than an error.
    send_campaign(camp)
    assert camp.status == Campaign.STATUS_SENT


@pytest.mark.django_db
def test_send_campaign_refuses_failed_campaign(list_with_subs, tenant):
    list_, _ = list_with_subs
    camp = create_campaign(
        tenant=tenant, target=list_,
        subject="Hi", html_body="<p>Hi</p>",
    )
    Campaign.objects.filter(pk=camp.pk).update(status=Campaign.STATUS_FAILED)
    camp.refresh_from_db()
    with pytest.raises(CampaignStateError):
        send_campaign(camp)


@pytest.mark.django_db
def test_send_campaign_batch_uses_dummy_backend(list_with_subs, tenant):
    """End-to-end through the Celery batch task — should populate outbox."""
    from newsletter_engine.tasks import send_campaign_batch

    list_, _ = list_with_subs
    camp = create_campaign(
        tenant=tenant, target=list_,
        subject="Hi {{name}}", html_body="<p>Hi</p>",
    )
    Campaign.objects.filter(pk=camp.pk).update(status=Campaign.STATUS_SENDING)
    camp.refresh_from_db()
    batches = fan_out(camp)
    assert batches

    DummyBackend.reset()
    send_campaign_batch(batches[0])

    assert len(DummyBackend.outbox) == 2
    # Each entry has the expected subject.
    assert all(e["subject"] == "Hi {{name}}" for e in DummyBackend.outbox)


@pytest.mark.django_db
def test_send_campaign_batch_stats_increment(list_with_subs, tenant):
    """After a batch sends, Campaign.sent_count should be > 0 and the
    campaign should auto-transition to SENT (since this is the only batch).
    """
    from newsletter_engine.tasks import send_campaign_batch

    list_, _ = list_with_subs
    camp = create_campaign(
        tenant=tenant, target=list_,
        subject="Hello", html_body="<p>Hello</p>",
    )
    Campaign.objects.filter(pk=camp.pk).update(status=Campaign.STATUS_SENDING)
    camp.refresh_from_db()
    for batch in fan_out(camp):
        send_campaign_batch(batch)
    camp.refresh_from_db()
    assert camp.sent_count == 2
    assert camp.status == Campaign.STATUS_SENT


@pytest.mark.django_db
def test_cancel_skips_pending_deliveries(list_with_subs, tenant):
    list_, _ = list_with_subs
    camp = create_campaign(
        tenant=tenant, target=list_,
        subject="Cancelled", html_body="<p>...</p>",
    )
    Campaign.objects.filter(pk=camp.pk).update(status=Campaign.STATUS_SENDING)
    camp.refresh_from_db()
    fan_out(camp)

    cancel_campaign(camp, reason="oops")
    camp.refresh_from_db()
    assert camp.status == Campaign.STATUS_CANCELLED
    statuses = set(Delivery.objects.filter(campaign=camp).values_list("status", flat=True))
    assert statuses == {Delivery.STATUS_SKIPPED}


@pytest.mark.django_db
def test_compute_stats_returns_counters(list_with_subs, tenant):
    list_, _ = list_with_subs
    camp = create_campaign(
        tenant=tenant, target=list_,
        subject="X", html_body="<p>x</p>",
    )
    Campaign.objects.filter(pk=camp.pk).update(status=Campaign.STATUS_SENDING)
    camp.refresh_from_db()
    fan_out(camp)
    update = compute_campaign_stats(camp)
    assert "sent_count" in update
    assert "open_count" in update
