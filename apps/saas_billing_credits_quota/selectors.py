"""Read-only queries for the billing subsystem.

Selectors never mutate state. They get_or_create the singletons (Subscription,
CreditBalance) but they don't change plan/status/balance — that's the
service layer's job.
"""
from __future__ import annotations

from typing import Iterable, Optional

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Sum

from .exceptions import InvalidPlan
from .models import (
    CreditBalance,
    CreditTransaction,
    MonthlyQuota,
    Subscription,
    _default_plan,
)


User = get_user_model()


# ---------------------------------------------------------------------------
# Plan-limit lookups
# ---------------------------------------------------------------------------

def plan_limits(plan: str) -> dict[str, Optional[int]]:
    """Return the ``{resource_key: limit}`` dict for a given plan slug.

    A value of ``None`` means "unlimited for this resource on this plan".
    An empty dict means "no limits configured" — which we treat as zero, not
    unlimited, because shipping with "everything is free" is a foot-gun.
    """
    table: dict[str, dict[str, Optional[int]]] = getattr(
        settings, "SAAS_PLAN_LIMITS", {},
    )
    if plan not in table:
        valid = list(table.keys())
        raise InvalidPlan(
            f"Plan '{plan}' is not in SAAS_PLAN_LIMITS. Valid plans: {valid}.",
        )
    return dict(table[plan])


def resource_limit(plan: str, resource_key: str) -> Optional[int]:
    """Return the plan's monthly limit for ``resource_key``.

    Returns ``None`` if the resource is unlimited on this plan; returns ``0``
    if the resource isn't listed (= not allowed).
    """
    return plan_limits(plan).get(resource_key, 0)


# ---------------------------------------------------------------------------
# Singleton lookups
# ---------------------------------------------------------------------------

def get_or_create_subscription(user) -> Subscription:
    """Idempotently fetch the user's Subscription row.

    Default plan = ``SAAS_DEFAULT_PLAN``. Use this everywhere instead of
    ``Subscription.objects.get(user=...)`` so signup never has to pre-seed.
    """
    sub, _ = Subscription.objects.get_or_create(user=user)
    return sub


def get_balance(user) -> int:
    """Current top-up credit balance. Creates the row lazily if missing."""
    bal, _ = CreditBalance.objects.get_or_create(user=user)
    return int(bal.balance)


def recent_transactions(user, n: int = 20) -> list[CreditTransaction]:
    """Last ``n`` credit transactions, newest first. Read-only."""
    return list(
        CreditTransaction.objects
        .filter(user=user)
        .order_by("-created_at")[:n]
    )


# ---------------------------------------------------------------------------
# Quota / usage lookups
# ---------------------------------------------------------------------------

def monthly_count(user, resource_key: str, month_key: Optional[str] = None) -> int:
    """Usage count for ``(user, resource_key, month_key)``.

    Defaults to the current month. Returns 0 if the row doesn't exist yet
    (== nothing consumed yet this month).
    """
    from .services import current_month_key
    key = month_key or current_month_key()
    row = (
        MonthlyQuota.objects
        .filter(user=user, resource_key=resource_key, month_key=key)
        .first()
    )
    return int(row.count) if row else 0


def effective_limit(user, resource_key: str) -> int:
    """Return ``plan_remaining + credits_available`` for ``resource_key``.

    This is the number the frontend should show as "you can still do X
    article generations this month" — it transparently includes top-up
    credits so a user with 0 quota left but 50 credits sees 50.

    ``None`` plan limits (unlimited) are reported as ``10**9`` here so the
    return type stays ``int`` — callers should treat huge values as effectively
    unlimited and check ``resource_limit() is None`` if the distinction matters.
    """
    sub = get_or_create_subscription(user)
    limit = resource_limit(sub.plan, resource_key)
    if limit is None:
        return 10**9  # sentinel "unlimited"
    used = monthly_count(user, resource_key)
    plan_remaining = max(0, limit - used)
    credits = get_balance(user)
    return plan_remaining + credits


def ledger_sum(user) -> int:
    """Sum of all CreditTransaction.amount rows for ``user``.

    Used by the admin to catch drift between ``CreditBalance.balance`` and
    the append-only ledger. They should match exactly.
    """
    agg = CreditTransaction.objects.filter(user=user).aggregate(s=Sum("amount"))
    return int(agg["s"] or 0)


def find_user_by_stripe_customer(stripe_customer_id: str):
    """Reverse-lookup the User attached to a Stripe customer_id.

    Returns ``None`` if no Subscription matches — caller (webhook) logs and
    drops the event in that case.
    """
    if not stripe_customer_id:
        return None
    sub = (
        Subscription.objects
        .filter(stripe_customer_id=stripe_customer_id)
        .select_related("user")
        .first()
    )
    return sub.user if sub else None
