"""Segment-evaluation tests (DSL exercised against a real DB)."""
from __future__ import annotations

import pytest

from newsletter_engine.models import (
    Segment,
    Subscriber,
    SubscriberTag,
)
from newsletter_engine.services.segments import (
    cache_segment_count,
    evaluate_segment,
)


@pytest.mark.django_db
def test_empty_filters_matches_all_confirmed(tenant, subscriber):
    """An empty Segment.filters dict means "every confirmed subscriber"."""
    seg = Segment.objects.create(tenant=tenant, name="All", filters={})
    qs = evaluate_segment(seg)
    assert subscriber in qs


@pytest.mark.django_db
def test_segment_excludes_unconfirmed_by_default(tenant, pending_subscriber):
    seg = Segment.objects.create(tenant=tenant, name="All", filters={})
    qs = evaluate_segment(seg)
    assert pending_subscriber not in qs


@pytest.mark.django_db
def test_include_unconfirmed_flag(tenant, pending_subscriber):
    seg = Segment.objects.create(tenant=tenant, name="All", filters={})
    qs = evaluate_segment(seg, include_unconfirmed=True)
    assert pending_subscriber in qs


@pytest.mark.django_db
def test_field_filter_locale(tenant, subscriber):
    """Confirmed subscriber has locale=fr — filter eq=fr matches."""
    seg = Segment.objects.create(
        tenant=tenant, name="French",
        filters={"op": "field", "field": "locale", "compare": "eq", "value": "fr"},
    )
    assert subscriber in evaluate_segment(seg)


@pytest.mark.django_db
def test_field_filter_excludes_non_matching(tenant, subscriber):
    seg = Segment.objects.create(
        tenant=tenant, name="English",
        filters={"op": "field", "field": "locale", "compare": "eq", "value": "en"},
    )
    assert subscriber not in evaluate_segment(seg)


@pytest.mark.django_db
def test_has_tag(tenant, subscriber, vip_tag):
    SubscriberTag.objects.create(subscriber=subscriber, tag=vip_tag)
    seg = Segment.objects.create(
        tenant=tenant, name="VIPs",
        filters={"op": "has_tag", "tag_id": vip_tag.pk},
    )
    assert subscriber in evaluate_segment(seg)


@pytest.mark.django_db
def test_has_tag_excludes_untagged(tenant, subscriber, vip_tag):
    seg = Segment.objects.create(
        tenant=tenant, name="VIPs",
        filters={"op": "has_tag", "tag_id": vip_tag.pk},
    )
    assert subscriber not in evaluate_segment(seg)


@pytest.mark.django_db
def test_tenant_isolation(tenant, other_tenant):
    """A subscriber under tenant A doesn't leak into tenant B's segment."""
    a_sub = Subscriber.objects.create(
        tenant=tenant, email="a@example.com",
        status=Subscriber.STATUS_CONFIRMED,
    )
    seg = Segment.objects.create(
        tenant=other_tenant, name="other",
        filters={},
    )
    assert a_sub not in evaluate_segment(seg)


@pytest.mark.django_db
def test_cache_segment_count_persists(tenant, subscriber):
    seg = Segment.objects.create(tenant=tenant, name="All", filters={})
    cache_segment_count(seg)
    seg.refresh_from_db()
    assert seg.subscriber_count == 1
    assert seg.last_evaluated_at is not None


@pytest.mark.django_db
def test_dsl_error_propagates_from_evaluate(tenant):
    seg = Segment.objects.create(
        tenant=tenant, name="bad",
        filters={"op": "no_such_op"},
    )
    from newsletter_engine.exceptions import SegmentDSLError
    with pytest.raises(SegmentDSLError):
        list(evaluate_segment(seg))
