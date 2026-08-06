"""Billing models — Subscription, CreditBalance, CreditTransaction, MonthlyQuota.

This template assumes one ``Subscription`` per user and one ``CreditBalance``
per user (both 1-to-1). Quota usage is tracked in ``MonthlyQuota`` rows keyed
by ``(user, resource_key, month_key)`` so a single user can have separate
budgets for separate resources (e.g. ``article_generation`` vs ``api_call``).

Why ``resource_key`` (string) instead of a FK to a ``Resource`` model?
The set of billed resources is small (3-10 in most projects) and known at
config time — adding a row to ``SAAS_PLAN_LIMITS`` is cheaper than running
a migration. CharField with ``db_index=True`` is fast enough for the lookups
we do.

Why ``month_key`` as ``YYYY-MM`` string instead of a date?
The "month" semantic is fuzzy (some apps want UTC months, some want local
months, some want billing-cycle months that don't align with calendar months).
A pre-formatted string lets the caller decide; the DB just stores opaque keys.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


# ---------------------------------------------------------------------------
# Configurable choices.
#
# Override in your project's settings:
#
#   SAAS_PLAN_CHOICES = [
#       ("free",   "Essai (gratuit)"),
#       ("solo",   "Solo"),
#       ("pro",    "Pro"),
#       ("agency", "Agence"),
#   ]
#   SAAS_DEFAULT_PLAN = "free"
#   SAAS_PLAN_LIMITS = {
#       "free":   {"article_generation": 1,   "api_call": 100},
#       "solo":   {"article_generation": 8,   "api_call": 1000},
#       "pro":    {"article_generation": 60,  "api_call": 10_000},
#       "agency": {"article_generation": 200, "api_call": None},  # unlimited
#   }
#
# Defaults below mirror blog-dashboard but are NOT product-specific — they're
# just illustrative.
# ---------------------------------------------------------------------------
DEFAULT_PLAN_CHOICES: list[tuple[str, str]] = [
    ("free",   "Free trial"),
    ("solo",   "Solo"),
    ("pro",    "Pro"),
    ("agency", "Agency"),
]
DEFAULT_STATUS_CHOICES: list[tuple[str, str]] = [
    ("active",     "Active"),
    ("trialing",   "Trialing"),
    ("past_due",   "Past due"),
    ("canceled",   "Cancelled"),
    ("incomplete", "Incomplete"),
    ("unpaid",     "Unpaid"),
]
DEFAULT_PLAN = "free"


def _plan_choices() -> list[tuple[str, str]]:
    return list(getattr(settings, "SAAS_PLAN_CHOICES", DEFAULT_PLAN_CHOICES))


def _default_plan() -> str:
    return getattr(settings, "SAAS_DEFAULT_PLAN", DEFAULT_PLAN)


class Subscription(models.Model):
    """One subscription row per user. Tracks the active plan + Stripe IDs.

    Created lazily by ``selectors.get_or_create_subscription`` on the first
    billing call. Mutated by the Stripe webhook (``services.update_subscription_from_stripe``).
    Never edit ``plan`` / ``status`` directly outside the webhook path — they
    must always reflect Stripe's source of truth.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="subscription",
    )
    plan = models.CharField(
        max_length=32,
        choices=_plan_choices(),
        default=_default_plan(),
        help_text="Plan slug. Must match a key in SAAS_PLAN_LIMITS.",
    )
    status = models.CharField(
        max_length=20,
        choices=DEFAULT_STATUS_CHOICES,
        default="active",
        help_text="Mirror of Stripe Subscription.status.",
    )
    stripe_customer_id = models.CharField(
        max_length=120,
        blank=True,
        default="",
        db_index=True,
        help_text="Stripe Customer.id (cus_xxx). Set on first checkout.",
    )
    stripe_subscription_id = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text="Stripe Subscription.id (sub_xxx). Empty for free plan.",
    )
    current_period_end = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When Stripe will charge the next renewal. NULL on free plan.",
    )
    cancel_at_period_end = models.BooleanField(
        default=False,
        help_text="True after the user clicked 'Cancel' but the current "
                  "billing period hasn't ended yet.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "saas_subscription"
        ordering = ("-updated_at",)
        indexes = [
            models.Index(fields=["stripe_customer_id"]),
            models.Index(fields=["plan", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} — {self.plan} ({self.status})"

    @property
    def is_paid(self) -> bool:
        """True when the user is on a paid plan AND payment is current."""
        return self.plan != _default_plan() and self.status in ("active", "trialing")


class CreditBalance(models.Model):
    """Top-up credit balance per user. One row per user. Credits never expire.

    Mutated atomically via ``services.add_credits`` / ``services.record_spend``
    using F() expressions to avoid race conditions on concurrent consume calls.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="credit_balance",
    )
    balance = models.PositiveIntegerField(
        default=0,
        help_text="Current credit balance. Always non-negative — debit is "
                  "atomic with a balance__gte=amount filter.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "saas_credit_balance"
        ordering = ("-updated_at",)

    def __str__(self) -> str:
        return f"{self.user_id}: {self.balance} credits"


class CreditTransaction(models.Model):
    """Append-only ledger of every credit movement.

    Rows are never updated or deleted, so ``sum(amount)`` for a given user
    should always equal that user's ``CreditBalance.balance``. The admin
    surfaces a sanity-check column to spot drift.

    ``amount`` is SIGNED: positive for purchase/refund/gift, negative for
    spend. This lets ``aggregate(Sum('amount'))`` give the running balance
    directly without joining anything else.
    """

    KIND_CHOICES = [
        ("purchase", "Purchase"),
        ("spend",    "Spend"),
        ("refund",   "Refund"),
        ("gift",     "Gift"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="credit_transactions",
    )
    amount = models.IntegerField(
        help_text="Positive for credits added, negative for spent. "
                  "Signed so the running balance = SUM(amount).",
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    resource_key = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_index=True,
        help_text="For 'spend' txns, the resource that was billed (e.g. "
                  "'article_generation'). Empty for purchase/refund/gift.",
    )
    stripe_session_id = models.CharField(
        max_length=120,
        blank=True,
        default="",
        db_index=True,
        help_text="Stripe Checkout Session id for purchase events. Used as "
                  "idempotency key — duplicate webhooks are NO-OP.",
    )
    description = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "saas_credit_transaction"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["kind", "-created_at"]),
        ]

    def __str__(self) -> str:
        sign = "+" if self.amount >= 0 else ""
        return f"{self.user_id} {sign}{self.amount} ({self.kind})"


class MonthlyQuota(models.Model):
    """Per-(user, resource, month) usage counter.

    Created lazily on the first consume of a month, then incremented atomically
    with ``F('count') + n``. A new month implicitly resets the counter because
    the (user, resource_key, month_key) uniqueness uses a fresh ``month_key``.

    The caller picks the resource_key string — this template doesn't enumerate
    valid resources, the ``SAAS_PLAN_LIMITS`` mapping is the source of truth
    for "what's billable".
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="monthly_quotas",
    )
    resource_key = models.CharField(
        max_length=64,
        db_index=True,
        help_text="Resource identifier matching keys in SAAS_PLAN_LIMITS "
                  "(e.g. 'article_generation', 'api_call', 'export').",
    )
    month_key = models.CharField(
        max_length=7,
        db_index=True,
        help_text="YYYY-MM. Generated by services.current_month_key() — "
                  "override if you need billing-cycle months.",
    )
    count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "saas_monthly_quota"
        ordering = ("-month_key", "resource_key")
        constraints = [
            models.UniqueConstraint(
                fields=["user", "resource_key", "month_key"],
                name="saas_quota_unique_user_resource_month",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "resource_key", "month_key"]),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} {self.resource_key} {self.month_key}: {self.count}"
