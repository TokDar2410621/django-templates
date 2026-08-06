"""Campaign creation, fan-out, sending, cancellation, stats.

Sending pipeline
----------------

1. ``create_campaign`` makes a ``draft`` row.
2. ``send_campaign`` (or the scheduled task that picks up ``status=scheduled``
   rows whose ``scheduled_at`` is in the past) transitions to ``sending``
   and enqueues ``tasks.fan_out_campaign``.
3. ``fan_out_campaign`` walks the target queryset, creates one ``Delivery``
   row per recipient, and enqueues ``tasks.send_campaign_batch`` for each
   batch.
4. Each batch calls the email backend, updates the Deliveries, and increments
   the Campaign counter via F() expressions.
5. When all Deliveries are out of ``pending``/``queued``, a final
   ``compute_campaign_stats`` flips the campaign to ``sent``.

We do NOT call the email backend synchronously from ``send_campaign`` —
that would block the HTTP request and fail any reasonably-sized list. The
caller MUST have a Celery worker running.

If you want a synchronous "send to one recipient now" for testing, that's
``backends.send_one`` directly — not exposed via the service layer because
it would tempt callers to bypass the queue in production.
"""
from __future__ import annotations

import logging
import secrets
from typing import Optional, Union

from django.db import transaction
from django.utils import timezone

from ..exceptions import CampaignStateError
from ..models import (
    Campaign,
    Delivery,
    MailingList,
    Membership,
    Segment,
    Subscriber,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
def create_campaign(
    *,
    tenant,
    target: Union[MailingList, Segment],
    subject: str,
    html_body: str,
    text_body: str = "",
    from_role: str = "",
    from_email_override: str = "",
    reply_to: str = "",
    scheduled_at=None,
    created_by=None,
) -> Campaign:
    """Persist a new draft (or scheduled) campaign.

    ``target`` is either a ``MailingList`` (campaign sends to every active
    member) or a ``Segment`` (campaign sends to whoever matches the DSL).
    The campaign starts in ``draft``; if ``scheduled_at`` is given, it's
    bumped to ``scheduled``.
    """
    if isinstance(target, MailingList):
        list_, segment = target, None
    elif isinstance(target, Segment):
        list_, segment = None, target
    else:
        raise TypeError("target must be a MailingList or Segment instance")

    camp = Campaign.objects.create(
        tenant=tenant,
        list=list_,
        segment=segment,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        from_role=from_role,
        from_email_override=from_email_override,
        reply_to=reply_to,
        scheduled_at=scheduled_at,
        status=Campaign.STATUS_SCHEDULED if scheduled_at else Campaign.STATUS_DRAFT,
        created_by=created_by,
    )
    logger.info(
        "newsletter.campaign.created id=%s subject=%r status=%s",
        camp.pk, camp.subject[:80], camp.status,
    )
    return camp


# ---------------------------------------------------------------------------
# Send (kick off fan-out)
# ---------------------------------------------------------------------------
def send_campaign(campaign: Campaign) -> Campaign:
    """Transition a campaign to ``sending`` and enqueue the fan-out.

    Idempotent on the campaign id: if the campaign is already in ``sending``
    or ``sent``, this is a no-op. Returns the (possibly mutated) campaign.

    Why no inline send? Because lists can have thousands of recipients;
    blocking the HTTP request would time out. The fan-out task creates
    Delivery rows and batches the actual SMTP calls.
    """
    if campaign.status in (Campaign.STATUS_SENT, Campaign.STATUS_SENDING):
        return campaign
    if campaign.status not in (Campaign.STATUS_DRAFT, Campaign.STATUS_SCHEDULED):
        raise CampaignStateError(campaign.status, "send")

    with transaction.atomic():
        Campaign.objects.filter(pk=campaign.pk).update(
            status=Campaign.STATUS_SENDING,
            sent_at=timezone.now(),
        )

    # Late import — avoid pulling celery in at module-load time.
    from ..tasks import fan_out_campaign
    fan_out_campaign.delay(campaign.pk)

    campaign.refresh_from_db(fields=["status", "sent_at"])
    logger.info("newsletter.campaign.send queued id=%s", campaign.pk)
    return campaign


def cancel_campaign(campaign: Campaign, *, reason: str = "") -> Campaign:
    """Mark a campaign cancelled and mark its pending deliveries skipped.

    Has no effect on already-sent Deliveries — once an email has gone out
    over SMTP there's nothing we can do. The intent is to stop the rest of
    the fan-out.
    """
    if campaign.status in (Campaign.STATUS_SENT, Campaign.STATUS_CANCELLED):
        return campaign

    with transaction.atomic():
        Campaign.objects.filter(pk=campaign.pk).update(
            status=Campaign.STATUS_CANCELLED,
        )
        Delivery.objects.filter(
            campaign=campaign,
            status__in=(Delivery.STATUS_PENDING, Delivery.STATUS_QUEUED),
        ).update(status=Delivery.STATUS_SKIPPED, error=reason or "cancelled")

    campaign.refresh_from_db(fields=["status"])
    logger.info("newsletter.campaign.cancel id=%s reason=%s", campaign.pk, reason)
    return campaign


# ---------------------------------------------------------------------------
# Build the recipient queryset
# ---------------------------------------------------------------------------
def recipients_queryset(campaign: Campaign):
    """The Subscriber queryset that this campaign targets.

    Always filtered to ``status=confirmed`` — bounced/complained/unsub
    subscribers are excluded at the source, so the fan-out never creates
    Delivery rows for them.
    """
    if campaign.list_id is not None:
        return Subscriber.objects.filter(
            tenant=campaign.tenant,
            status=Subscriber.STATUS_CONFIRMED,
            memberships__list_id=campaign.list_id,
            memberships__status=Membership.STATUS_ACTIVE,
        ).distinct()
    # Segment path.
    from .segments import evaluate_segment
    return evaluate_segment(campaign.segment)


# ---------------------------------------------------------------------------
# Fan-out — called from the Celery task
# ---------------------------------------------------------------------------
def _new_tracking_token() -> str:
    return secrets.token_urlsafe(24)


def fan_out(campaign: Campaign, *, batch_size: int = 100) -> list[list[int]]:
    """Create Delivery rows for every recipient and return batches of IDs.

    Idempotent: a re-run of fan_out sees existing Delivery rows (unique
    (campaign, subscriber)) and skips them via ignore_conflicts=True.

    Returns a list of lists; the outer list is the batch grouping the task
    will submit, the inner list contains the Delivery PKs.
    """
    qs = recipients_queryset(campaign).only("pk")
    sub_ids = list(qs.values_list("pk", flat=True))

    # Bulk-create with ignore_conflicts so re-running is safe.
    to_create = [
        Delivery(
            campaign=campaign,
            subscriber_id=sid,
            tracking_token=_new_tracking_token(),
            status=Delivery.STATUS_QUEUED,
        )
        for sid in sub_ids
    ]
    Delivery.objects.bulk_create(to_create, ignore_conflicts=True, batch_size=500)

    # Now collect the actual PKs (some may have been ignored).
    all_pks = list(
        Delivery.objects
        .filter(campaign=campaign, status=Delivery.STATUS_QUEUED)
        .values_list("pk", flat=True)
    )
    batches = [
        all_pks[i:i + batch_size] for i in range(0, len(all_pks), batch_size)
    ]
    logger.info(
        "newsletter.campaign.fanout id=%s recipients=%d batches=%d",
        campaign.pk, len(all_pks), len(batches),
    )
    return batches


# ---------------------------------------------------------------------------
# Stats — invoked after every batch finishes
# ---------------------------------------------------------------------------
def compute_campaign_stats(campaign: Campaign) -> dict[str, int]:
    """Recompute and persist the cached counters on a campaign.

    Called both after every batch (cheap, lets the admin show progress) and
    at the very end (to flip the campaign to ``sent``).
    """
    by_status: dict[str, int] = {}
    for row in Delivery.objects.filter(campaign=campaign).values("status"):
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1

    sent = (
        by_status.get(Delivery.STATUS_SENT, 0)
        + by_status.get(Delivery.STATUS_DELIVERED, 0)
        + by_status.get(Delivery.STATUS_OPENED, 0)
        + by_status.get(Delivery.STATUS_CLICKED, 0)
        + by_status.get(Delivery.STATUS_BOUNCED, 0)
        + by_status.get(Delivery.STATUS_COMPLAINED, 0)
    )
    update = dict(
        sent_count=sent,
        delivered_count=(
            by_status.get(Delivery.STATUS_DELIVERED, 0)
            + by_status.get(Delivery.STATUS_OPENED, 0)
            + by_status.get(Delivery.STATUS_CLICKED, 0)
        ),
        open_count=by_status.get(Delivery.STATUS_OPENED, 0) + by_status.get(Delivery.STATUS_CLICKED, 0),
        click_count=by_status.get(Delivery.STATUS_CLICKED, 0),
        bounce_count=by_status.get(Delivery.STATUS_BOUNCED, 0),
        complaint_count=by_status.get(Delivery.STATUS_COMPLAINED, 0),
    )

    pending_left = (
        by_status.get(Delivery.STATUS_PENDING, 0)
        + by_status.get(Delivery.STATUS_QUEUED, 0)
    )
    if pending_left == 0 and campaign.status == Campaign.STATUS_SENDING:
        update["status"] = Campaign.STATUS_SENT

    Campaign.objects.filter(pk=campaign.pk).update(**update)
    logger.debug("newsletter.campaign.stats id=%s %s", campaign.pk, update)
    return update
