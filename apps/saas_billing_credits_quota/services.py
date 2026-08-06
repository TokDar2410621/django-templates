"""Billing services — mutate state atomically.

Three guarantees this module makes:

1. **Credit balance never drifts.** All mutations of ``CreditBalance.balance``
   go through ``add_credits`` or ``record_spend``, both of which use F()
   expressions inside a single UPDATE statement so concurrent consume calls
   from different workers can't interleave a read-modify-write.

2. **Spend is debit-or-fail.** ``record_spend`` filters on
   ``balance__gte=amount`` so the UPDATE matches zero rows if the user is
   broke — we don't go negative.

3. **Webhook idempotency.** ``add_credits`` with a non-empty
   ``stripe_session_id`` checks for an existing purchase txn and short-circuits
   if found. Stripe re-delivers webhooks on flaky network — this is the only
   thing standing between that and double-credits.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone as _tz
from typing import Optional

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .exceptions import QuotaExceeded
from .models import (
    CreditBalance,
    CreditTransaction,
    MonthlyQuota,
    Subscription,
)
from .selectors import (
    get_balance,
    get_or_create_subscription,
    monthly_count,
    resource_limit,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Month-key helpers
# ---------------------------------------------------------------------------

def current_month_key() -> str:
    """Return YYYY-MM for "now" in the project's active timezone.

    Override by patching this function in tests or by writing your own
    billing-cycle key if your billing cycles don't align with calendar months.
    """
    now = timezone.now()
    return f"{now.year:04d}-{now.month:02d}"


# ---------------------------------------------------------------------------
# Consume — the hot path
# ---------------------------------------------------------------------------

@transaction.atomic
def consume(user, resource_key: str, n: int = 1) -> str:
    """Consume ``n`` units of ``resource_key`` for ``user``.

    Order of operations:

    1. If the plan limit is unlimited (``None``), increment the monthly counter
       and return ``"quota"``.
    2. If plan limit isn't exceeded after incrementing by ``n``, do it and
       return ``"quota"``.
    3. Else fall back to credits — atomically debit ``n`` from balance and
       return ``"credit"``.
    4. If neither bucket can cover the call, raise ``QuotaExceeded``.

    The whole thing runs in a single transaction so a concurrent call from
    another worker can't see the "between buckets" state. Returns the bucket
    name so callers can surface "this used your monthly quota" vs "this used
    a credit" to the user.
    """
    if n <= 0:
        raise ValueError("n must be positive")

    sub = get_or_create_subscription(user)
    limit = resource_limit(sub.plan, resource_key)

    if limit is None:
        _increment_monthly(user, resource_key, n)
        logger.debug(
            "saas.consume bucket=quota_unlimited user=%s resource=%s n=%d",
            user.pk, resource_key, n,
        )
        return "quota"

    used = monthly_count(user, resource_key)
    if used + n <= limit:
        _increment_monthly(user, resource_key, n)
        logger.debug(
            "saas.consume bucket=quota user=%s resource=%s n=%d used=%d/%d",
            user.pk, resource_key, n, used + n, limit,
        )
        return "quota"

    # Plan quota exhausted (or would be after this call) — try credits.
    if _atomic_debit(user, n, resource_key=resource_key):
        logger.info(
            "saas.consume bucket=credit user=%s resource=%s n=%d (plan exhausted)",
            user.pk, resource_key, n,
        )
        return "credit"

    raise QuotaExceeded(
        resource_key=resource_key,
        plan_limit=limit,
        current_count=used,
        credits_available=get_balance(user),
        requested=n,
    )


def record_spend(user, resource_key: str, amount: int) -> bool:
    """Public wrapper for credit-only spend (no quota check, no fallback).

    Use when you've already decided the call MUST come from credits (e.g.
    the user is on the free plan and you want to charge per-call without
    monthly quotas at all). Returns True on success, False if balance was
    insufficient.
    """
    return _atomic_debit(user, amount, resource_key=resource_key)


# ---------------------------------------------------------------------------
# Credit-balance mutations
# ---------------------------------------------------------------------------

@transaction.atomic
def add_credits(
    user,
    amount: int,
    *,
    kind: str = "purchase",
    stripe_session_id: str = "",
    description: str = "",
) -> int:
    """Atomically credit ``amount`` to the user's balance + log a txn.

    Idempotent on ``stripe_session_id`` for ``kind="purchase"`` — duplicate
    webhook deliveries return the current balance without double-crediting.

    Returns the new balance.
    """
    if amount <= 0:
        raise ValueError("amount must be positive (use record_spend to debit)")
    if kind == "purchase" and stripe_session_id:
        if CreditTransaction.objects.filter(
            stripe_session_id=stripe_session_id,
            kind="purchase",
        ).exists():
            logger.info(
                "saas.add_credits idempotent skip session=%s user=%s",
                stripe_session_id, user.pk,
            )
            return get_balance(user)

    bal, _ = CreditBalance.objects.get_or_create(user=user)
    CreditBalance.objects.filter(pk=bal.pk).update(balance=F("balance") + amount)
    CreditTransaction.objects.create(
        user=user,
        amount=amount,
        kind=kind,
        stripe_session_id=stripe_session_id,
        description=description,
    )
    bal.refresh_from_db(fields=["balance"])
    logger.info(
        "saas.add_credits user=%s kind=%s amount=%d new_balance=%d",
        user.pk, kind, amount, bal.balance,
    )
    return int(bal.balance)


def _atomic_debit(user, amount: int, *, resource_key: str = "") -> bool:
    """Debit ``amount`` from balance with a guard against going negative.

    The UPDATE filters on ``balance__gte=amount`` so concurrent callers can't
    both pass a read-side balance check and then race the UPDATE down to
    negative. Returns True only when the UPDATE actually changed a row.
    """
    if amount <= 0:
        raise ValueError("amount must be positive")
    affected = (
        CreditBalance.objects
        .filter(user=user, balance__gte=amount)
        .update(balance=F("balance") - amount)
    )
    if not affected:
        return False
    CreditTransaction.objects.create(
        user=user,
        amount=-amount,
        kind="spend",
        resource_key=resource_key,
        description=f"Spend on {resource_key}" if resource_key else "Spend",
    )
    return True


# ---------------------------------------------------------------------------
# Monthly counter
# ---------------------------------------------------------------------------

def _increment_monthly(user, resource_key: str, n: int) -> int:
    """Increment the (user, resource_key, current_month) counter by ``n``.

    Creates the row on first call of the month. Always returns the new count.
    """
    key = current_month_key()
    row, created = MonthlyQuota.objects.get_or_create(
        user=user,
        resource_key=resource_key,
        month_key=key,
        defaults={"count": n},
    )
    if created:
        return n
    MonthlyQuota.objects.filter(pk=row.pk).update(count=F("count") + n)
    row.refresh_from_db(fields=["count"])
    return int(row.count)


# ---------------------------------------------------------------------------
# Stripe — apply event data to Subscription rows
# ---------------------------------------------------------------------------

def update_subscription_from_stripe(user, stripe_event_data: dict) -> Subscription:
    """Mirror a Stripe Subscription object into our ``Subscription`` row.

    Accepts the ``data.object`` payload of a ``customer.subscription.*`` event.
    Looks up the plan by matching the ``items[0].price.id`` against the
    ``SAAS_PLAN_LIMITS``-aware price registry below.

    The registry is built from ``settings.SAAS_PLAN_STRIPE_PRICES = {
    "<plan_slug>": "<env var name>"}`` — operators set ``STRIPE_PRICE_PRO=price_xxx``
    in their env and we resolve it at webhook time.
    """
    import os
    sub = get_or_create_subscription(user)

    sub.stripe_subscription_id = stripe_event_data.get("id", "") or ""
    sub.status = stripe_event_data.get("status", "active") or "active"
    sub.cancel_at_period_end = bool(
        stripe_event_data.get("cancel_at_period_end"),
    )

    # Try to map the active price back to a plan slug.
    items = (stripe_event_data.get("items") or {}).get("data") or []
    if items:
        price_id = ((items[0].get("price") or {}).get("id")) or ""
        registry: dict[str, str] = getattr(
            settings, "SAAS_PLAN_STRIPE_PRICES", {},
        )
        for plan_slug, env_var in registry.items():
            if os.environ.get(env_var) == price_id:
                sub.plan = plan_slug
                break

    period_end = stripe_event_data.get("current_period_end")
    if period_end:
        sub.current_period_end = datetime.fromtimestamp(period_end, tz=_tz.utc)

    if (stripe_event_data.get("status") == "canceled"
            or stripe_event_data.get("ended_at")):
        sub.plan = getattr(settings, "SAAS_DEFAULT_PLAN", "free")
        sub.status = "canceled"

    sub.save()
    logger.info(
        "saas.subscription_updated user=%s plan=%s status=%s sub_id=%s",
        user.pk, sub.plan, sub.status, sub.stripe_subscription_id,
    )
    return sub


def attach_stripe_customer(user, stripe_customer_id: str) -> Subscription:
    """Idempotently set the user's stripe_customer_id."""
    sub = get_or_create_subscription(user)
    if sub.stripe_customer_id != stripe_customer_id:
        sub.stripe_customer_id = stripe_customer_id
        sub.save(update_fields=["stripe_customer_id"])
    return sub


def mark_past_due(user) -> Optional[Subscription]:
    """Flip status to past_due. Called from invoice.payment_failed."""
    sub = Subscription.objects.filter(user=user).first()
    if not sub:
        return None
    if sub.status != "past_due":
        sub.status = "past_due"
        sub.save(update_fields=["status"])
    return sub


def mark_active(user) -> Optional[Subscription]:
    """Flip status to active. Called from invoice.payment_succeeded."""
    sub = Subscription.objects.filter(user=user).first()
    if not sub:
        return None
    if sub.status != "active":
        sub.status = "active"
        sub.save(update_fields=["status"])
    return sub
