"""Segment evaluation services.

Thin wrapper around ``segment_dsl.compile_to_q`` that also:
  * scopes the queryset to ``tenant`` (defense-in-depth — even if the DSL
    forgot a tenant filter, this layer adds it)
  * filters to ``status=confirmed`` by default (a "VIP" segment should not
    include bounced subscribers)
  * restricts to active list memberships when the segment is list-scoped
"""
from __future__ import annotations

import logging

from django.db.models import QuerySet
from django.utils import timezone

from ..models import Membership, Segment, Subscriber
from ..segment_dsl import compile_to_q

logger = logging.getLogger(__name__)


def evaluate_segment(segment: Segment, *, include_unconfirmed: bool = False) -> QuerySet[Subscriber]:
    """Return a queryset of Subscribers matching this segment.

    By default, only confirmed subscribers are included. Set
    ``include_unconfirmed=True`` for admin previews where you want to see
    "potential" subscribers regardless of status.
    """
    q = compile_to_q(segment.filters)
    qs = Subscriber.objects.filter(tenant=segment.tenant).filter(q)
    if not include_unconfirmed:
        qs = qs.filter(status=Subscriber.STATUS_CONFIRMED)
    if segment.list_id is not None:
        # Restrict to active memberships of the segment's list.
        qs = qs.filter(
            memberships__list_id=segment.list_id,
            memberships__status=Membership.STATUS_ACTIVE,
        ).distinct()
    return qs


def cache_segment_count(segment: Segment) -> int:
    """Refresh the cached subscriber_count + last_evaluated_at on a Segment.

    Designed to be called from a Celery task on a schedule (segments that
    track engagement windows change daily) OR ad-hoc when an admin opens
    the segment detail page.
    """
    count = evaluate_segment(segment).count()
    Segment.objects.filter(pk=segment.pk).update(
        subscriber_count=count,
        last_evaluated_at=timezone.now(),
    )
    segment.subscriber_count = count
    logger.debug("newsletter.segment.cache id=%s count=%d", segment.pk, count)
    return count
