"""Automation services — enroll, tick, dispatch.

Lifecycle
---------
1. A trigger fires (signup, list_joined, tag_added, manual…) and calls
   ``handle_trigger`` which creates an ``AutomationEnrollment`` for every
   matching active Automation.
2. ``process_due_enrollments`` is invoked by Celery beat every N minutes
   (see ``tasks.process_automation_tick``). It finds enrollments whose
   "next step is due" and calls ``tick_automation`` on each.
3. ``tick_automation`` fires the next step's email (subject to its DSL
   condition), updates ``last_step_index`` + ``last_step_at``, and marks
   the enrollment ``completed`` once all steps are done.

Idempotency
-----------
Enrolling the same subscriber twice in the same automation is a no-op when
there's an active enrollment. To re-enroll, cancel the existing enrollment
first.

A worker crash mid-tick leaves ``last_step_index`` unchanged — the next
tick will retry the step. Email backends are responsible for de-duping
sends with their own provider-side mechanisms (we keep a Delivery-like
row in the step's send via the campaign machinery? — see Outstanding TODO
in README).
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Iterable, Optional

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from ..exceptions import AutomationTriggerError
from ..models import (
    Automation,
    AutomationEnrollment,
    AutomationStep,
    Subscriber,
)
from ..segment_dsl import compile_to_q

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enroll
# ---------------------------------------------------------------------------
@transaction.atomic
def enroll_subscriber(
    automation: Automation, subscriber: Subscriber,
) -> AutomationEnrollment:
    """Create (or re-use) an active enrollment for this subscriber.

    If a completed/cancelled enrollment exists, this method creates a fresh
    enrollment — we use ``get_or_create`` only when an active enrollment
    matches, otherwise we resurrect by creating a new row (deleting the old
    row preserves audit; we don't do that).

    Returns the active enrollment.
    """
    if not automation.is_active:
        raise AutomationTriggerError(
            f"Automation '{automation.name}' is inactive — refusing to enroll"
        )
    active = AutomationEnrollment.objects.filter(
        automation=automation, subscriber=subscriber,
        completed_at__isnull=True, cancelled_at__isnull=True,
    ).first()
    if active is not None:
        return active

    # Re-enroll: the unique constraint is on (automation, subscriber). If a
    # completed row exists, we can't insert another. We "reset" the existing
    # row by clearing completion/cancellation and resetting last_step_index.
    existing = AutomationEnrollment.objects.filter(
        automation=automation, subscriber=subscriber,
    ).first()
    if existing is not None:
        existing.completed_at = None
        existing.cancelled_at = None
        existing.cancellation_reason = ""
        existing.last_step_index = -1
        existing.last_step_at = None
        existing.started_at = timezone.now()
        existing.save()
        return existing

    return AutomationEnrollment.objects.create(
        automation=automation, subscriber=subscriber,
    )


def handle_trigger(
    *,
    tenant,
    trigger: str,
    subscriber: Subscriber,
    context: Optional[dict] = None,
) -> list[AutomationEnrollment]:
    """Enroll a subscriber in every active Automation matching ``trigger``.

    ``context`` carries trigger-specific data:
        signup        -> {}
        list_joined   -> {"list_id": <int>}
        tag_added     -> {"tag_id": <int>}
        manual        -> {"automation_id": <int>}
        anniversary   -> {}

    Automations declare their own ``trigger_config`` which is matched
    against the context (e.g. an automation with trigger='list_joined' +
    trigger_config={"list_id": 3} only fires when context["list_id"] == 3).
    """
    context = context or {}
    enrollments: list[AutomationEnrollment] = []

    qs = Automation.objects.filter(
        tenant=tenant, trigger=trigger, is_active=True,
    )

    for auto in qs:
        if not _trigger_matches(auto, context):
            continue
        enrollments.append(enroll_subscriber(auto, subscriber))
    return enrollments


def _trigger_matches(automation: Automation, context: dict) -> bool:
    """Cheap matcher: every key in trigger_config must equal context's value.

    Empty trigger_config matches anything.
    """
    cfg = automation.trigger_config or {}
    for k, v in cfg.items():
        if context.get(k) != v:
            return False
    return True


# ---------------------------------------------------------------------------
# Tick
# ---------------------------------------------------------------------------
def _next_step(automation: Automation, last_index: int) -> Optional[AutomationStep]:
    return (
        AutomationStep.objects
        .filter(automation=automation, order__gt=last_index)
        .order_by("order")
        .first()
    )


def _is_due(enrollment: AutomationEnrollment, step: AutomationStep, now=None) -> bool:
    """True iff ``step``'s delay has elapsed since the previous step (or
    enrollment start, for the first step).
    """
    now = now or timezone.now()
    anchor = enrollment.last_step_at or enrollment.started_at
    return (now - anchor) >= timedelta(seconds=step.delay_seconds)


@transaction.atomic
def tick_automation(
    enrollment: AutomationEnrollment, *, now=None,
) -> Optional[AutomationStep]:
    """Advance one step on an enrollment if due.

    Returns the step that fired, or None if nothing fired (not yet due,
    cancelled, or already completed).
    """
    if not enrollment.is_active:
        return None
    now = now or timezone.now()

    step = _next_step(enrollment.automation, enrollment.last_step_index)
    if step is None:
        # Out of steps — mark completed.
        AutomationEnrollment.objects.filter(pk=enrollment.pk).update(
            completed_at=now,
        )
        return None

    if not _is_due(enrollment, step, now=now):
        return None

    # Check the step's condition (Segment DSL). If the subscriber doesn't
    # match, we SKIP this step (no email) but still advance the index.
    cond = step.condition or {}
    condition_passed = True
    if cond:
        q = compile_to_q(cond)
        condition_passed = Subscriber.objects.filter(
            pk=enrollment.subscriber_id,
        ).filter(q).exists()

    if condition_passed:
        _deliver_step(enrollment, step)

    AutomationEnrollment.objects.filter(pk=enrollment.pk).update(
        last_step_index=step.order,
        last_step_at=now,
    )
    logger.info(
        "newsletter.automation.tick enroll=%s step=%s fired=%s",
        enrollment.pk, step.order, condition_passed,
    )
    return step


def _deliver_step(enrollment: AutomationEnrollment, step: AutomationStep) -> None:
    """Render + send the step's email to the enrollment's subscriber.

    Routes through the configured email backend. We do NOT create a
    Delivery row here — automation steps are 1:1:1 (automation, step,
    subscriber) and the audit is the enrollment itself. If you need
    open/click tracking on automation emails, see Outstanding TODOs.
    """
    from ..backends import get_email_backend
    from .subscribers import create_unsubscribe_token

    sub = enrollment.subscriber
    if not sub.is_sendable:
        logger.debug(
            "newsletter.automation.step skip unsendable enroll=%s sub=%s status=%s",
            enrollment.pk, sub.pk, sub.status,
        )
        return

    token = create_unsubscribe_token(sub, scope="all")
    from django.conf import settings
    base = (
        getattr(settings, "NEWSLETTER_TRACKING_BASE_URL", "")
        or getattr(settings, "FRONTEND_BASE_URL", "")
        or ""
    ).rstrip("/")
    unsub_url = f"{base}/newsletter/unsubscribe/?token={token.token}"

    backend = get_email_backend()
    backend.send(
        to=sub.email,
        subject=step.subject,
        html=step.html_body,
        text=step.text_body or _strip_html(step.html_body),
        from_email=getattr(settings, "NEWSLETTER_DEFAULT_FROM_EMAIL", "noreply@example.com"),
        reply_to=getattr(settings, "NEWSLETTER_DEFAULT_REPLY_TO", ""),
        headers={
            "List-Unsubscribe": f"<{unsub_url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
    )


def _strip_html(html: str) -> str:
    """Naive HTML->text — replace tags with spaces. Good enough for fallback."""
    import re
    return re.sub(r"<[^>]+>", " ", html or "").replace("&nbsp;", " ").strip()


# ---------------------------------------------------------------------------
# Beat-target entry point
# ---------------------------------------------------------------------------
def due_enrollments(*, limit: int = 500, now=None) -> Iterable[AutomationEnrollment]:
    """Find enrollments that COULD fire a step right now.

    The "due" computation is a bit too dynamic for SQL — we narrow with a
    coarse filter (active enrollments + automation active) and let
    ``tick_automation`` re-check the precise delay in Python. ``limit``
    caps the batch so a single tick never grows unbounded.
    """
    now = now or timezone.now()
    return (
        AutomationEnrollment.objects
        .filter(
            completed_at__isnull=True,
            cancelled_at__isnull=True,
            automation__is_active=True,
        )
        .select_related("automation", "subscriber")
        .order_by("last_step_at")[:limit]
    )


def process_due_enrollments(*, limit: int = 500, now=None) -> int:
    """Iterate due enrollments + tick each one. Returns the count ticked."""
    n = 0
    for enr in due_enrollments(limit=limit, now=now):
        step = tick_automation(enr, now=now)
        if step is not None:
            n += 1
    return n
