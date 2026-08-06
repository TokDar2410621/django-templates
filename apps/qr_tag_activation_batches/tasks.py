"""Celery tasks for qr_tag_activation_batches.

Wire into your Celery Beat schedule (hourly is a sensible default)::

    # config/celery.py
    app.conf.beat_schedule = {
        "qr-tag-confirm-provisional-claims": {
            "task": "qr_tag_activation_batches.confirm_provisional_claims",
            "schedule": crontab(minute=0),  # every hour
        },
    }
"""
from __future__ import annotations

import logging

from celery import shared_task

from . import services

logger = logging.getLogger(__name__)


@shared_task(name="qr_tag_activation_batches.confirm_provisional_claims")
def confirm_provisional_claims() -> dict:
    """Promote PROVISIONAL photo-claims past their dispute window.

    Returns a dict with counts of each outcome, useful for monitoring
    and for spotting abnormal dispute volumes::

        {"confirmed": 12, "disputed": 1}

    The window length is :setting:`ACTIVATION_PROVISIONAL_HOURS`
    (default 48 hours).
    """
    confirmed, disputed = services.confirm_provisional()
    if confirmed or disputed:
        logger.info(
            "qr_tag_activation_batches.confirm_provisional_claims "
            "confirmed=%d sent_to_admin=%d",
            confirmed, disputed,
        )
    return {"confirmed": confirmed, "disputed": disputed}
