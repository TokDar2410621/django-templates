"""Celery tasks for newsletter_engine.

Beat schedule snippet (copy into your project's ``CELERY_BEAT_SCHEDULE``)::

    CELERY_BEAT_SCHEDULE = {
        "newsletter-automation-tick": {
            "task": "newsletter_engine.tasks.process_automation_tick",
            "schedule": 300,  # every 5 minutes
        },
        "newsletter-scheduled-campaigns": {
            "task": "newsletter_engine.tasks.process_scheduled_campaigns",
            "schedule": 60,  # every minute
        },
        "newsletter-bounces-decay": {
            "task": "newsletter_engine.tasks.process_bounces_decay",
            "schedule": 86400,  # daily
        },
    }

If your project doesn't use Celery, you can call the underlying service
functions directly from a ``manage.py`` management command on a cron tick —
the tasks are thin wrappers.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.db.models import F
from django.utils import timezone

logger = logging.getLogger(__name__)


def _batch_size() -> int:
    return int(getattr(settings, "NEWSLETTER_BATCH_SIZE", 100))


# ---------------------------------------------------------------------------
# Celery decorator — fall back to a passthrough if Celery isn't installed
# (lets the app boot in degraded mode without celery in requirements).
# ---------------------------------------------------------------------------
try:
    from celery import shared_task
except ImportError:  # pragma: no cover - celery is optional at install-time
    def shared_task(*args, **kwargs):
        def _wrap(fn):
            fn.delay = fn  # type: ignore[attr-defined]
            return fn
        if args and callable(args[0]):
            return _wrap(args[0])
        return _wrap


# ---------------------------------------------------------------------------
# Fan-out + batches
# ---------------------------------------------------------------------------
@shared_task
def fan_out_campaign(campaign_id: int) -> dict:
    """Create Delivery rows for a campaign + enqueue send_campaign_batch tasks.

    Idempotent: re-running this for the same campaign sees existing
    Delivery rows (unique constraint) and only schedules batches for rows
    still in ``queued`` status.
    """
    from .models import Campaign
    from .services.campaigns import fan_out

    camp = Campaign.objects.filter(pk=campaign_id).first()
    if camp is None:
        logger.warning("fan_out_campaign: campaign %s not found", campaign_id)
        return {"ok": False, "reason": "not_found"}

    if camp.status != Campaign.STATUS_SENDING:
        logger.info(
            "fan_out_campaign: campaign %s not in SENDING (status=%s) — skip",
            campaign_id, camp.status,
        )
        return {"ok": False, "reason": "wrong_status", "status": camp.status}

    batches = fan_out(camp, batch_size=_batch_size())
    for batch in batches:
        send_campaign_batch.delay(batch)
    return {"ok": True, "campaign_id": campaign_id, "batch_count": len(batches)}


@shared_task
def send_campaign_batch(delivery_ids: list[int]) -> dict:
    """Send the email for each Delivery in this batch.

    Updates Delivery.status + Campaign.sent_count atomically. Errors on
    individual sends are recorded on the row; the whole batch never aborts.
    """
    from .backends import get_email_backend
    from .models import Campaign, Delivery
    from .services.campaigns import compute_campaign_stats
    from .services.subscribers import create_unsubscribe_token
    from .services.tracking import rewrite_html_for_tracking

    backend = get_email_backend()
    base_unsub_url = (
        getattr(settings, "NEWSLETTER_TRACKING_BASE_URL", "")
        or getattr(settings, "FRONTEND_BASE_URL", "")
        or ""
    ).rstrip("/")

    sent_count = 0
    fail_count = 0
    skip_count = 0
    campaign_id: int | None = None

    deliveries = (
        Delivery.objects
        .filter(pk__in=delivery_ids)
        .select_related("subscriber", "campaign")
    )
    for delivery in deliveries:
        campaign_id = delivery.campaign_id
        sub = delivery.subscriber
        if not sub.is_sendable:
            Delivery.objects.filter(pk=delivery.pk).update(
                status=Delivery.STATUS_SKIPPED,
                error=f"subscriber unsendable: {sub.status}",
            )
            skip_count += 1
            continue

        campaign = delivery.campaign
        # Build unsub token (scoped to this list / global).
        scope = (
            f"list:{campaign.list.slug}" if campaign.list_id
            else "all"
        )
        tok = create_unsubscribe_token(sub, scope=scope)
        unsub_url = f"{base_unsub_url}/api/newsletter/unsubscribe/?token={tok.token}"

        html = rewrite_html_for_tracking(campaign.html_body, delivery)
        text = campaign.text_body or ""

        from_email = (
            campaign.from_email_override
            or getattr(settings, "NEWSLETTER_DEFAULT_FROM_EMAIL", "")
            or "noreply@example.com"
        )
        reply_to = campaign.reply_to or (
            campaign.list.default_reply_to if campaign.list_id else ""
        ) or getattr(settings, "NEWSLETTER_DEFAULT_REPLY_TO", "")

        result = backend.send(
            to=sub.email,
            subject=campaign.subject,
            html=html,
            text=text,
            from_email=from_email,
            reply_to=reply_to,
            headers={
                "List-Unsubscribe": f"<{unsub_url}>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            },
        )

        if result.ok:
            Delivery.objects.filter(pk=delivery.pk).update(
                status=Delivery.STATUS_SENT,
                provider_message_id=result.provider_message_id,
                sent_at=timezone.now(),
            )
            Campaign.objects.filter(pk=campaign_id).update(
                sent_count=F("sent_count") + 1,
            )
            sent_count += 1
        else:
            Delivery.objects.filter(pk=delivery.pk).update(
                status=Delivery.STATUS_FAILED,
                error=(result.error or "")[:1000],
            )
            fail_count += 1

    # Recompute campaign-level stats so the admin sees fresh counters,
    # and so the campaign auto-transitions to ``sent`` if this was the last
    # batch.
    if campaign_id is not None:
        from .models import Campaign
        camp = Campaign.objects.filter(pk=campaign_id).first()
        if camp is not None:
            compute_campaign_stats(camp)

    return {
        "ok": True,
        "sent": sent_count,
        "failed": fail_count,
        "skipped": skip_count,
        "campaign_id": campaign_id,
    }


# ---------------------------------------------------------------------------
# Beat targets
# ---------------------------------------------------------------------------
@shared_task
def process_automation_tick() -> dict:
    """Find due automation enrollments + advance them.

    Beat schedule: every 5 minutes.
    """
    from .services.automations import process_due_enrollments
    n = process_due_enrollments(limit=500)
    return {"ok": True, "ticked": n}


@shared_task
def process_scheduled_campaigns() -> dict:
    """Send any campaign whose scheduled_at is in the past.

    Beat schedule: every minute.
    """
    from .selectors import campaigns_ready_to_send
    from .services.campaigns import send_campaign as svc_send
    count = 0
    for camp in campaigns_ready_to_send():
        svc_send(camp)
        count += 1
    return {"ok": True, "sent": count}


@shared_task
def process_bounces_decay() -> dict:
    """Decay bounce_count on subscribers whose last bounce was long ago.

    Beat schedule: daily. Configurable decay window via
    ``NEWSLETTER_BOUNCE_DECAY_DAYS`` (default 30).
    """
    from .models import Subscriber
    days = int(getattr(settings, "NEWSLETTER_BOUNCE_DECAY_DAYS", 30))
    threshold = timezone.now() - timedelta(days=days)
    n = (
        Subscriber.objects
        .filter(bounce_count__gt=0, last_bounce_at__lt=threshold)
        .exclude(status=Subscriber.STATUS_BOUNCED)
        .update(bounce_count=0)
    )
    return {"ok": True, "decayed": n}
