"""Services — Stripe Connect OAuth, payout math, transfer dispatch.

Layered split:

  - Pure functions (``compute_payout``) — no I/O, no Stripe calls.
    Trivially unit-testable. Same input → same output.
  - I/O functions (``create_payout``, ``handle_connect_callback``,
    ``reverse_payout``) — wrap Stripe SDK calls in transactions and
    write to the Payout ledger.

Stripe SDK is imported lazily inside the I/O functions so that
``compute_payout`` can run without ``stripe`` installed (handy for
test cases that don't need network mocks).
"""
from __future__ import annotations

import logging
from typing import Iterable, Optional, TypedDict
from urllib.parse import urlencode

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.utils import timezone

from .models import Affiliate, Partner, PartnerProductShare, Payout

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class StripeNotConfigured(Exception):
    """Raised when Stripe credentials are missing."""


class PartnerNotPayable(Exception):
    """Raised when a partner can't receive a Stripe Transfer right now.

    Reasons: ``stripe_account_id`` empty, ``stripe_account_verified``
    False, or ``active`` False.
    """


# ---------------------------------------------------------------------------
# Pure math — no I/O.
# ---------------------------------------------------------------------------

class PayoutComputation(TypedDict):
    gross_cents: int
    share_bps: int
    partner_amount_cents: int
    platform_fee_cents: int


def compute_payout(
    *,
    gross_cents: int,
    partner: Partner,
    external_product_id: Optional[str] = None,
    share_bps_override: Optional[int] = None,
) -> PayoutComputation:
    """Return how a line gross splits between platform and partner.

    Resolution order for the share:
      1. ``share_bps_override`` if provided (caller-level override —
         the line-item knows its own deal, e.g. promotional pricing).
      2. ``PartnerProductShare(partner, external_product_id)`` if it
         exists (SKU-level override).
      3. ``partner.default_share_bps`` (catch-all default).

    ``partner.flat_per_order_cents`` is always subtracted FIRST, before
    the share is applied — that models "cover the cost of goods, then
    split the markup".

    Math::

        net      = max(gross - flat_per_order_cents, 0)
        partner  = floor(net * share_bps / 10_000)
        platform = gross - partner
    """
    if gross_cents < 0:
        raise ValueError("gross_cents must be non-negative")

    # Resolve share.
    if share_bps_override is not None:
        share_bps = int(share_bps_override)
    else:
        share_bps = _resolve_share_bps(partner, external_product_id)

    if not (0 <= share_bps <= 10_000):
        raise ValueError(f"share_bps out of range: {share_bps}")

    flat = max(int(partner.flat_per_order_cents or 0), 0)
    net = max(int(gross_cents) - flat, 0)
    partner_amount = (net * share_bps) // 10_000  # integer floor
    partner_amount = max(partner_amount, 0)
    # Platform pockets the difference (covers the flat fee + its share
    # of the remainder).
    platform_fee = max(int(gross_cents) - partner_amount, 0)
    return {
        "gross_cents": int(gross_cents),
        "share_bps": share_bps,
        "partner_amount_cents": partner_amount,
        "platform_fee_cents": platform_fee,
    }


def _resolve_share_bps(partner: Partner, external_product_id: Optional[str]) -> int:
    if external_product_id:
        override = (
            PartnerProductShare.objects
            .filter(partner=partner, external_product_id=external_product_id)
            .values_list("share_bps", flat=True)
            .first()
        )
        if override is not None:
            return int(override)
    return int(partner.default_share_bps)


# ---------------------------------------------------------------------------
# Stripe Connect OAuth flow (Standard accounts).
# ---------------------------------------------------------------------------

OAUTH_STATE_MAX_AGE_SECONDS = 600  # 10 min — Stripe's recommendation


def _oauth_signer() -> signing.TimestampSigner:
    return signing.TimestampSigner(salt="stripe-connect-multivendor-oauth-v1")


def make_oauth_state(partner: Partner) -> str:
    """Sign a state token binding the OAuth round-trip to one partner."""
    return _oauth_signer().sign(f"partner:{partner.pk}")


def parse_oauth_state(token: str) -> int:
    """Verify the signed token and return the bound partner PK.

    Raises ``django.core.signing.SignatureExpired`` (>10min old) or
    ``signing.BadSignature`` (forged / tampered).
    """
    raw = _oauth_signer().unsign(token, max_age=OAUTH_STATE_MAX_AGE_SECONDS)
    _kind, _, pk = raw.partition(":")
    return int(pk)


def connect_oauth_url(
    partner: Partner,
    *,
    return_url: Optional[str] = None,
) -> str:
    """Build the Stripe OAuth ``authorize`` URL for this partner.

    Requires ``STRIPE_CONNECT_CLIENT_ID`` (the ``ca_xxx`` platform ID)
    to be set in Django settings. Optional ``return_url`` overrides
    the redirect URI registered on the Stripe dashboard.
    """
    client_id = getattr(settings, "STRIPE_CONNECT_CLIENT_ID", "")
    if not client_id:
        raise StripeNotConfigured(
            "STRIPE_CONNECT_CLIENT_ID not configured. Find it at "
            "https://dashboard.stripe.com/settings/connect"
        )
    params = {
        "response_type": "code",
        "client_id": client_id,
        "scope": "read_write",
        "state": make_oauth_state(partner),
        "stripe_user[email]": partner.payout_email or partner.user.email or "",
    }
    if return_url:
        params["redirect_uri"] = return_url
    return "https://connect.stripe.com/oauth/authorize?" + urlencode(params)


def handle_connect_callback(*, code: str, partner: Partner) -> None:
    """Exchange the OAuth ``code`` for an account ID and stamp the partner.

    Also requests the ``transfers`` capability (idempotent on Stripe's
    side). The capability may stay "pending" until the partner finishes
    bank verification on their side; the ``account.updated`` webhook
    will flip ``stripe_account_verified`` when Stripe enables it.
    """
    import stripe

    _require_secret_key()
    resp = stripe.OAuth.token(grant_type="authorization_code", code=code)
    account_id = resp["stripe_user_id"]

    verified = _request_transfers_capability(account_id)

    partner.stripe_account_id = account_id
    partner.stripe_account_verified = verified
    partner.save(
        update_fields=["stripe_account_id", "stripe_account_verified"]
    )
    logger.info(
        "scm.connect.linked partner=%s account=%s verified=%s",
        partner.pk, account_id, verified,
    )


def _request_transfers_capability(account_id: str) -> bool:
    """Request the ``transfers`` capability and return its active state.

    For Standard accounts (which we own no platform control over), the
    ``Account.modify`` call may raise PermissionError — Stripe's polite
    way of saying "the partner manages their own capabilities". Falls
    back to a read-only ``Account.retrieve``.

    Returns True when ``transfers == 'active'`` OR when both
    ``charges_enabled`` and ``payouts_enabled`` are true (the same
    "ready" proxy the webhook uses).
    """
    import stripe

    try:
        account = stripe.Account.modify(
            account_id,
            capabilities={
                "transfers": {"requested": True},
                "card_payments": {"requested": True},
            },
        )
    except stripe.error.PermissionError:
        account = stripe.Account.retrieve(account_id)
    capabilities = account.get("capabilities") or {}
    if capabilities.get("transfers") == "active":
        return True
    return bool(
        account.get("charges_enabled") and account.get("payouts_enabled")
    )


# ---------------------------------------------------------------------------
# Payout creation & dispatch.
# ---------------------------------------------------------------------------

def _require_secret_key() -> None:
    """Ensure ``stripe.api_key`` is set before any I/O call."""
    import stripe

    key = getattr(settings, "STRIPE_SECRET_KEY", "")
    if not key:
        raise StripeNotConfigured(
            "STRIPE_SECRET_KEY is not configured. See SETTINGS.md."
        )
    stripe.api_key = key


def _partner_payable(partner: Partner) -> bool:
    return bool(
        partner.active
        and partner.stripe_account_id
        and partner.stripe_account_verified
    )


@transaction.atomic
def create_payout(
    *,
    partner: Partner,
    external_order_id: str,
    external_order_item_id: str,
    gross_cents: int,
    external_product_id: Optional[str] = None,
    share_bps_override: Optional[int] = None,
    currency: Optional[str] = None,
) -> Payout:
    """Create (or refresh) a payout row and fire the Stripe Transfer.

    Atomic: compute → upsert pending row → ``stripe.Transfer.create`` →
    update row to PAID/FAILED → commit.

    Idempotency:
      - ``unique_together(external_order_item_id, partner)`` guarantees
        one row per (item, partner). Re-calls update in place.
      - ``idempotency_key="scm_payout_<pk>"`` lets Stripe deduplicate
        retries server-side.

    Already-paid rows are returned unchanged (never overwrite a real
    transfer ID). Failed rows are retried.
    """
    import stripe

    from .settings_helpers import stripe_default_currency

    currency = (currency or stripe_default_currency()).upper()

    computation = compute_payout(
        gross_cents=gross_cents,
        partner=partner,
        external_product_id=external_product_id,
        share_bps_override=share_bps_override,
    )

    payout, created = Payout.objects.get_or_create(
        partner=partner,
        external_order_item_id=external_order_item_id,
        defaults={
            "external_order_id": external_order_id,
            "gross_cents": computation["gross_cents"],
            "share_bps": computation["share_bps"],
            "partner_amount_cents": computation["partner_amount_cents"],
            "platform_fee_cents": computation["platform_fee_cents"],
            "currency": currency,
            "status": Payout.STATUS_PENDING,
        },
    )

    if payout.status == Payout.STATUS_PAID:
        # Real money already moved — don't touch.
        return payout

    if payout.status == Payout.STATUS_REVERSED:
        # Reversed transfers must be re-created manually with a new
        # idempotency_key — return as-is so the caller sees the state.
        return payout

    # Refresh computation on retry — math could have changed if the
    # share_bps was tweaked between the failure and the retry.
    if not created:
        payout.gross_cents = computation["gross_cents"]
        payout.share_bps = computation["share_bps"]
        payout.partner_amount_cents = computation["partner_amount_cents"]
        payout.platform_fee_cents = computation["platform_fee_cents"]
        payout.currency = currency
        payout.status = Payout.STATUS_PENDING
        payout.error = ""
        payout.save(update_fields=[
            "gross_cents", "share_bps", "partner_amount_cents",
            "platform_fee_cents", "currency", "status", "error",
        ])

    # Zero-amount payouts: no transfer needed, but the row stays as a
    # record. Mark PAID immediately (nothing owed = nothing pending).
    if payout.partner_amount_cents <= 0:
        payout.status = Payout.STATUS_PAID
        payout.paid_at = timezone.now()
        payout.save(update_fields=["status", "paid_at"])
        return payout

    if not _partner_payable(partner):
        # Don't dispatch — leave PENDING so an operator can fix Connect
        # state and retry. Raise so the caller knows nothing moved.
        raise PartnerNotPayable(
            f"Partner #{partner.pk} cannot receive transfers right now "
            f"(active={partner.active}, "
            f"acct={bool(partner.stripe_account_id)}, "
            f"verified={partner.stripe_account_verified})."
        )

    _require_secret_key()

    try:
        transfer = stripe.Transfer.create(
            amount=payout.partner_amount_cents,
            # Stripe expects lowercase currency codes.
            currency=currency.lower(),
            destination=partner.stripe_account_id,
            transfer_group=f"order_{external_order_id}",
            metadata={
                "scm_payout_id": str(payout.pk),
                "partner_id": str(partner.pk),
                "external_order_id": external_order_id,
                "external_order_item_id": external_order_item_id,
            },
            idempotency_key=f"scm_payout_{payout.pk}",
        )
    except stripe.error.StripeError as exc:
        payout.status = Payout.STATUS_FAILED
        payout.error = str(exc)
        payout.save(update_fields=["status", "error"])
        logger.exception(
            "scm.payout.failed payout=%s partner=%s order=%s",
            payout.pk, partner.pk, external_order_id,
        )
        return payout

    payout.stripe_transfer_id = transfer.id
    payout.status = Payout.STATUS_PAID
    payout.paid_at = timezone.now()
    payout.error = ""
    payout.save(update_fields=[
        "stripe_transfer_id", "status", "paid_at", "error",
    ])
    logger.info(
        "scm.payout.paid payout=%s partner=%s amount=%dc transfer=%s",
        payout.pk, partner.pk, payout.partner_amount_cents, transfer.id,
    )
    return payout


class LineItem(TypedDict, total=False):
    external_order_item_id: str
    gross_cents: int
    partner_id: int
    external_product_id: str
    share_bps_override: int


def bulk_payout_for_order(
    *,
    external_order_id: str,
    line_items: Iterable[LineItem],
    currency: Optional[str] = None,
) -> list[Payout]:
    """Run ``create_payout`` for every line in one order.

    ``line_items`` is a sequence of dicts shaped like ``LineItem``.
    Each line generates one Payout row tied to one Partner.

    Collects (doesn't raise) per-line errors so a single broken line
    doesn't block the others — failed rows land in the returned list
    with ``status=failed``. ``PartnerNotPayable`` is caught and recorded
    on the row as a failure with a descriptive error message so the
    operator can retry later.
    """
    results: list[Payout] = []
    for line in line_items:
        try:
            partner = Partner.objects.get(pk=line["partner_id"])
        except Partner.DoesNotExist:
            logger.warning(
                "scm.bulk.unknown_partner order=%s line=%s partner_id=%s",
                external_order_id,
                line.get("external_order_item_id"),
                line.get("partner_id"),
            )
            continue
        try:
            payout = create_payout(
                partner=partner,
                external_order_id=external_order_id,
                external_order_item_id=line["external_order_item_id"],
                gross_cents=int(line["gross_cents"]),
                external_product_id=line.get("external_product_id"),
                share_bps_override=line.get("share_bps_override"),
                currency=currency,
            )
        except PartnerNotPayable as exc:
            # Record the row anyway, FAILED, so the dashboard surfaces
            # the missing-Connect-state problem to the operator.
            payout, _ = Payout.objects.get_or_create(
                partner=partner,
                external_order_item_id=line["external_order_item_id"],
                defaults={
                    "external_order_id": external_order_id,
                    "gross_cents": int(line["gross_cents"]),
                    "share_bps": 0,
                    "partner_amount_cents": 0,
                    "platform_fee_cents": int(line["gross_cents"]),
                    "currency": (currency or "CAD").upper(),
                    "status": Payout.STATUS_FAILED,
                    "error": str(exc),
                },
            )
            if payout.status == Payout.STATUS_PENDING:
                payout.status = Payout.STATUS_FAILED
                payout.error = str(exc)
                payout.save(update_fields=["status", "error"])
        results.append(payout)
    return results


@transaction.atomic
def reverse_payout(payout: Payout, *, reason: str = "") -> Payout:
    """Reverse a paid Stripe Transfer and mark the row REVERSED.

    Calls ``stripe.Transfer.create_reversal`` (idempotent on Stripe's
    side via the transfer ID) and flips the row's status. Use this
    when the customer is refunded for an item that already triggered
    a partner payout — the platform claws back the partner's cut.

    Raises ``ValueError`` if the payout isn't in PAID state.
    """
    if payout.status != Payout.STATUS_PAID:
        raise ValueError(
            f"Cannot reverse payout #{payout.pk} in status={payout.status}"
        )
    if not payout.stripe_transfer_id:
        raise ValueError(
            f"Payout #{payout.pk} has no stripe_transfer_id"
        )

    import stripe

    _require_secret_key()
    stripe.Transfer.create_reversal(
        payout.stripe_transfer_id,
        metadata={
            "scm_payout_id": str(payout.pk),
            "reason": reason or "manual_reverse",
        },
        idempotency_key=f"scm_payout_{payout.pk}_reversal",
    )
    payout.status = Payout.STATUS_REVERSED
    if reason:
        payout.error = f"reversed: {reason}"
    payout.save(update_fields=["status", "error"])
    logger.info(
        "scm.payout.reversed payout=%s transfer=%s reason=%s",
        payout.pk, payout.stripe_transfer_id, reason,
    )
    return payout
