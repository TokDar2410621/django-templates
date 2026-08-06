"""Concurrent-consume race tests for the atomic F() patterns.

We can't easily test true concurrency in a unit test (the SQLite Django uses
in CI doesn't model row-level locks the same way Postgres does), but we CAN
verify that:

1. Sequential consume calls each see the previous one's update before
   deciding the bucket.
2. Manual concurrent ``UPDATE balance = balance - X`` collisions never go
   negative — the WHERE clause filters out rows that would.

Run these tests against your production Postgres for a real test of the race
condition guard (set ``DATABASES`` to point at a scratch Postgres DB).
"""
from __future__ import annotations

import threading

import pytest

from saas_billing_credits_quota.models import CreditBalance, CreditTransaction
from saas_billing_credits_quota.selectors import get_balance, monthly_count
from saas_billing_credits_quota.services import (
    _atomic_debit,
    _increment_monthly,
    add_credits,
    consume,
)


@pytest.mark.django_db
def test_atomic_debit_never_goes_negative(user, plan_limits):
    """Two consecutive 5-credit debits when balance is 7 → one succeeds, one fails."""
    add_credits(user, 7, kind="gift")
    assert _atomic_debit(user, 5, resource_key="x") is True
    assert get_balance(user) == 2
    assert _atomic_debit(user, 5, resource_key="x") is False  # not enough
    assert get_balance(user) == 2  # unchanged


@pytest.mark.django_db
def test_increment_monthly_creates_then_bumps(user, plan_limits):
    """First call creates a row; subsequent calls F()-increment it."""
    assert _increment_monthly(user, "api_call", 1) == 1
    assert _increment_monthly(user, "api_call", 2) == 3
    assert _increment_monthly(user, "api_call", 1) == 4
    assert monthly_count(user, "api_call") == 4


@pytest.mark.django_db
def test_consume_sequence_decrements_in_order(user, plan_limits):
    """Sequential consume calls all see the latest state — no stale reads."""
    from saas_billing_credits_quota.selectors import get_or_create_subscription
    sub = get_or_create_subscription(user)
    sub.plan = "solo"  # 8 articles/month
    sub.save()

    for i in range(1, 9):
        consume(user, "article_generation", n=1)
        assert monthly_count(user, "article_generation") == i
    # Quota exhausted; next call needs credits and should raise.
    from saas_billing_credits_quota.exceptions import QuotaExceeded
    with pytest.raises(QuotaExceeded):
        consume(user, "article_generation")


@pytest.mark.django_db(transaction=True)
def test_concurrent_consume_does_not_double_spend_credits(user, plan_limits):
    """Two threads racing to spend the last credit — only one wins.

    Marked transaction=True so each thread runs in its own transaction
    instead of the test's wrapping transaction (which would serialize them).
    Skipped silently on SQLite where threading + database access is fragile;
    Postgres handles this correctly.
    """
    from django.db import connection
    if connection.vendor == "sqlite":
        pytest.skip("SQLite + threading is unreliable; run this on Postgres")

    add_credits(user, 1, kind="gift")  # exactly one credit available
    successes: list[bool] = []
    lock = threading.Lock()

    def worker():
        from django.db import connection as conn
        try:
            ok = _atomic_debit(user, 1, resource_key="race")
        finally:
            conn.close()
        with lock:
            successes.append(ok)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(successes) == 1, "exactly one debit must win"
    assert get_balance(user) == 0
    # And exactly one spend transaction was logged
    assert CreditTransaction.objects.filter(
        user=user, kind="spend",
    ).count() == 1
