"""Models for multi-vendor Stripe Connect payouts.

This template stays intentionally decoupled from the calling project's
order/product models. The link is by **string** keys (``external_order_id``
and ``external_order_item_id``) — your project owns the order schema,
this app only records who got paid what, when.

Why basis points (bps)?
    A basis point is 1/100th of a percent — 7000 bps = 70.00%. Storing
    integers instead of Decimal/float removes every rounding-vs-precision
    debate and matches Stripe's own ``application_fee_amount`` style.
    Conversion: ``percent = bps / 100``, ``share_fraction = bps / 10_000``.

Why the ``Payout`` ledger is append-only:
    A payout that hit Stripe is a real-world financial event. We never
    UPDATE the gross/share columns after the fact — only ``status``,
    ``stripe_transfer_id``, ``error``, and ``paid_at`` move forward.
    Reversal is its own status, not a delete. The calling project can
    audit-trail every transfer from this single table.
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models


# ---------------------------------------------------------------------------
# Partner — a user with the "vendor" role.
# ---------------------------------------------------------------------------

class Partner(models.Model):
    """A vendor who receives a share of each sale.

    One-to-one with the calling project's user model on purpose:
    partners ARE users (they need to log in, see their own dashboard,
    initiate the OAuth flow). Use a custom role/group on the User model
    if you need to gate "partner" features in your own views.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="partner_profile",
    )

    display_name = models.CharField(
        max_length=120,
        help_text="Public-facing name shown on receipts and dashboards.",
    )
    payout_email = models.EmailField(
        blank=True,
        help_text=(
            "Email Stripe uses to identify the partner during the OAuth "
            "handshake. Defaults to the user's email if blank."
        ),
    )

    # Stripe Connect Standard — partner connects an existing Stripe
    # account via OAuth. ``acct_xxx`` is empty until the OAuth callback
    # completes; ``verified`` flips True when the account.updated
    # webhook reports active capabilities.
    stripe_account_id = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        help_text="Stripe account ID (acct_…) once OAuth has linked one.",
    )
    stripe_account_verified = models.BooleanField(
        default=False,
        db_index=True,
        help_text=(
            "True once Stripe confirms the account can receive transfers "
            "(set by the account.updated webhook or by the OAuth callback)."
        ),
    )

    # Default revenue share for this partner — basis points (7000 = 70%).
    # Per-SKU overrides live in ``PartnerProductShare``.
    default_share_bps = models.PositiveIntegerField(
        default=7000,
        help_text=(
            "Default share in basis points. 7000 = 70.00%. The platform "
            "keeps the remainder (10000 - share)."
        ),
    )
    # Optional flat fee per ORDER item that gets deducted BEFORE the
    # share is applied (e.g. cover cost-of-goods on a $5 sticker before
    # splitting the markup). 0 disables.
    flat_per_order_cents = models.PositiveIntegerField(
        default=0,
        help_text=(
            "Optional flat deduction per order item, in cents. Subtracted "
            "from the gross BEFORE the share is computed. 0 disables."
        ),
    )

    active = models.BooleanField(
        default=True,
        help_text="Uncheck to suspend payouts without deleting the row.",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "scm_partner"
        ordering = ("display_name",)
        verbose_name = "Stripe Connect partner"
        verbose_name_plural = "Stripe Connect partners"

    def __str__(self) -> str:
        return self.display_name

    @property
    def share_percent(self) -> Decimal:
        """Convenience accessor — basis points rendered as a Decimal %.

        ``7000 bps`` → ``Decimal('70.00')``.
        """
        return Decimal(self.default_share_bps) / Decimal("100")


# ---------------------------------------------------------------------------
# Per-SKU share override.
# ---------------------------------------------------------------------------

class PartnerProductShare(models.Model):
    """Override a partner's default share for a specific SKU.

    Keyed by ``external_product_id`` (a string the calling project owns
    — could be a UUID, a slug, a Stripe Product ID, anything). The point
    is that this template never imports the project's Product model.

    Resolution: when computing a payout, ``compute_payout`` looks up
    ``(partner, external_product_id)`` first; if no row exists, falls
    back to ``Partner.default_share_bps``.
    """

    partner = models.ForeignKey(
        Partner,
        on_delete=models.CASCADE,
        related_name="product_shares",
    )
    external_product_id = models.CharField(
        max_length=128,
        help_text=(
            "Identifier from your project's Product model. Could be a "
            "UUID, slug, SKU, or external_id — whatever you key by."
        ),
    )
    share_bps = models.PositiveIntegerField(
        help_text="Override share, in basis points. 7000 = 70.00%.",
    )
    notes = models.CharField(
        max_length=200,
        blank=True,
        help_text="Internal note (reason for the override). Optional.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "scm_partner_product_share"
        unique_together = (("partner", "external_product_id"),)
        ordering = ("partner__display_name", "external_product_id")
        verbose_name = "Per-SKU share override"
        verbose_name_plural = "Per-SKU share overrides"

    def __str__(self) -> str:
        return f"{self.partner.display_name} / {self.external_product_id}"


# ---------------------------------------------------------------------------
# Payout ledger — append-only.
# ---------------------------------------------------------------------------

class Payout(models.Model):
    """One row per (order item, partner) pair = one Stripe Transfer.

    Status lifecycle::

        PENDING ──create_payout()──► PAID         (transfer succeeded)
            │
            └────create_payout()──► FAILED        (Stripe rejected)
                                       │
                                       └─(retry)─► PAID

        PAID ──reverse_payout()──► REVERSED       (after manual refund)

    REVERSED is set either by the ``transfer.reversed`` webhook OR by
    explicit ``reverse_payout()``. Once REVERSED, no further automatic
    transfer attempts are made for that row.
    """

    STATUS_PENDING = "pending"
    STATUS_PAID = "paid"
    STATUS_FAILED = "failed"
    STATUS_REVERSED = "reversed"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_PAID, "Paid"),
        (STATUS_FAILED, "Failed"),
        (STATUS_REVERSED, "Reversed"),
    )

    partner = models.ForeignKey(
        Partner,
        on_delete=models.PROTECT,
        related_name="payouts",
        help_text=(
            "PROTECT: deleting a Partner with payout history is blocked "
            "to preserve the financial audit trail. Soft-archive via the "
            "``active`` flag instead."
        ),
    )

    # The calling project's order keys. Strings so we never need to
    # import the project's models — this app stays a clean plug-in.
    external_order_id = models.CharField(max_length=128, db_index=True)
    external_order_item_id = models.CharField(max_length=128, db_index=True)

    # Captured at creation time. Never updated.
    gross_cents = models.PositiveIntegerField(
        help_text="Line gross (in cents) at payout-creation time.",
    )
    share_bps = models.PositiveIntegerField(
        help_text="Share applied (in basis points) at payout-creation time.",
    )
    partner_amount_cents = models.PositiveIntegerField(
        help_text="Amount transferred to the partner (in cents).",
    )
    platform_fee_cents = models.PositiveIntegerField(
        help_text="Amount the platform kept (gross - partner_amount).",
    )
    currency = models.CharField(
        max_length=8,
        default="CAD",
        help_text="ISO 4217 code, uppercase. Stripe expects lowercase at API time.",
    )

    # Outcome fields — written by ``create_payout`` and webhook handlers.
    stripe_transfer_id = models.CharField(
        max_length=120,
        blank=True,
        db_index=True,
        help_text="``tr_xxx`` from Stripe once the transfer succeeds.",
    )
    status = models.CharField(
        max_length=12,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    error = models.TextField(
        blank=True,
        help_text="Last Stripe error message if status == failed.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "scm_payout"
        ordering = ("-created_at",)
        # One payout per (item, partner). Idempotent re-runs find the
        # existing row instead of creating a duplicate.
        unique_together = (("external_order_item_id", "partner"),)
        indexes = [
            models.Index(fields=["partner", "status"]),
            models.Index(fields=["external_order_id", "status"]),
            models.Index(fields=["paid_at"]),
        ]

    def __str__(self) -> str:
        return (
            f"Payout #{self.pk or '?'} "
            f"{self.partner_amount_cents}¢ "
            f"{self.currency} "
            f"[{self.status}]"
        )


# ---------------------------------------------------------------------------
# Affiliate (optional sub-feature).
# ---------------------------------------------------------------------------

class Affiliate(models.Model):
    """Promo-code holder. Earns commission on attributed orders.

    Optional — your project can ignore this model entirely if you
    don't need referrals. Kept here because the calling pattern
    (compute → create Stripe Transfer → record) is identical to
    Partner, just keyed off the order's subtotal rather than per-item.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="affiliate_profile",
    )
    code = models.CharField(
        max_length=40,
        unique=True,
        help_text="Promo code customers enter at checkout (case-insensitive).",
    )
    commission_bps = models.PositiveIntegerField(
        default=1000,
        help_text="Commission in basis points. 1000 = 10.00% of subtotal.",
    )
    flat_per_order_cents = models.PositiveIntegerField(
        default=0,
        help_text=(
            "Flat amount per order using the code, in cents. Used when "
            "you want a fixed referral fee rather than a percentage. "
            "If non-zero, takes priority over ``commission_bps``."
        ),
    )

    stripe_account_id = models.CharField(max_length=100, blank=True)
    stripe_account_verified = models.BooleanField(default=False)

    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "scm_affiliate"
        ordering = ("code",)

    def __str__(self) -> str:
        return f"Affiliate {self.code}"
