"""Happy path + 2 negatives + credit fallback for ``services.consume``."""
from __future__ import annotations

import pytest

from saas_billing_credits_quota.exceptions import QuotaExceeded
from saas_billing_credits_quota.selectors import (
    effective_limit,
    get_balance,
    monthly_count,
)
from saas_billing_credits_quota.services import add_credits, consume


@pytest.mark.django_db
def test_consume_uses_quota_first(free_user):
    """Happy path: plan limit not exceeded → quota bucket used."""
    bucket = consume(free_user, "article_generation", n=1)
    assert bucket == "quota"
    assert monthly_count(free_user, "article_generation") == 1
    assert get_balance(free_user) == 0  # credits untouched


@pytest.mark.django_db
def test_consume_falls_back_to_credits_when_quota_exhausted(free_user):
    """Free plan = 1 article/month. Add credits; second call uses one."""
    # Burn the single free quota
    assert consume(free_user, "article_generation") == "quota"
    # Top up
    add_credits(free_user, 5, kind="gift")
    assert get_balance(free_user) == 5
    # Next consume must use a credit (plan exhausted)
    bucket = consume(free_user, "article_generation", n=1)
    assert bucket == "credit"
    assert get_balance(free_user) == 4
    assert monthly_count(free_user, "article_generation") == 1  # unchanged


@pytest.mark.django_db
def test_consume_raises_when_both_buckets_empty(free_user):
    """Negative #1: no quota, no credits → QuotaExceeded."""
    consume(free_user, "article_generation")  # burn the 1/month
    with pytest.raises(QuotaExceeded) as exc:
        consume(free_user, "article_generation")
    assert exc.value.resource_key == "article_generation"
    assert exc.value.plan_limit == 1
    assert exc.value.credits_available == 0


@pytest.mark.django_db
def test_consume_unknown_resource_acts_as_zero_limit(free_user):
    """Negative #2: a resource key not in SAAS_PLAN_LIMITS → effective limit 0."""
    # No credits, no quota line for "export" → consume must fail
    with pytest.raises(QuotaExceeded):
        consume(free_user, "export")


@pytest.mark.django_db
def test_consume_unlimited_plan_does_not_touch_credits(user, plan_limits):
    """``api_call`` is unlimited on pro plan → never debits credits even with
    a huge n."""
    from saas_billing_credits_quota.selectors import get_or_create_subscription
    sub = get_or_create_subscription(user)
    sub.plan = "pro"
    sub.save()
    add_credits(user, 100, kind="gift")
    bucket = consume(user, "api_call", n=999_999)
    assert bucket == "quota"
    assert get_balance(user) == 100


@pytest.mark.django_db
def test_consume_respects_n_greater_than_one(free_user):
    """Consuming n=3 against a limit of 8 (solo plan) just bumps the counter."""
    from saas_billing_credits_quota.selectors import get_or_create_subscription
    sub = get_or_create_subscription(free_user)
    sub.plan = "solo"
    sub.save()
    bucket = consume(free_user, "article_generation", n=3)
    assert bucket == "quota"
    assert monthly_count(free_user, "article_generation") == 3


@pytest.mark.django_db
def test_consume_rejects_non_positive_n(free_user):
    with pytest.raises(ValueError):
        consume(free_user, "article_generation", n=0)
    with pytest.raises(ValueError):
        consume(free_user, "article_generation", n=-1)


@pytest.mark.django_db
def test_effective_limit_includes_credits(free_user):
    """effective_limit = (plan_remaining + credits) on bounded resources."""
    # Free plan, 1 quota, 0 credits → 1
    assert effective_limit(free_user, "article_generation") == 1
    # Burn the quota → 0 remaining, 0 credits → 0
    consume(free_user, "article_generation")
    assert effective_limit(free_user, "article_generation") == 0
    # Add 5 credits → 0 remaining + 5 credits = 5
    add_credits(free_user, 5, kind="gift")
    assert effective_limit(free_user, "article_generation") == 5
