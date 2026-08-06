"""Stripe Connect webhook router.

Handles the three event types this template cares about:

  - ``account.updated``    — partner finished onboarding / capabilities
                              changed → sync ``stripe_account_verified``
  - ``transfer.created``   — confirm we recorded the transfer ID we
                              expected (link if missing)
  - ``transfer.reversed``  — Stripe reversed a transfer → mark our
                              ledger row REVERSED

Mount the ``StripeWebhookView`` in your urls. Stripe sends a signed
payload; we verify against ``STRIPE_WEBHOOK_SECRET`` (the Connect
endpoint signing secret, not the Account endpoint one — they differ
when the platform has both).
"""
from __future__ import annotations

import logging
from typing import Optional

from django.conf import settings

from .models import Partner, Payout

logger = logging.getLogger(__name__)


def construct_event(payload: bytes, sig_header: str):
    """Verify the signature and return the parsed Stripe ``Event``.

    Raises ``stripe.SignatureVerificationError`` on signature mismatch.
    """
    import stripe

    secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", "")
    if not secret:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET is not configured.")
    return stripe.Webhook.construct_event(payload, sig_header, secret)


def dispatch_event(event: dict) -> Optional[str]:
    """Route a verified Stripe Event to the matching handler.

    Returns the event type that was handled (or None if ignored) for
    logging / observability in the calling view.
    """
    event_type = event.get("type", "")
    obj = event.get("data", {}).get("object", {}) or {}

    if event_type == "account.updated":
        _on_account_updated(obj)
        return event_type
    if event_type == "transfer.created":
        _on_transfer_created(obj)
        return event_type
    if event_type == "transfer.reversed":
        _on_transfer_reversed(obj)
        return event_type
    return None


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def _on_account_updated(account: dict) -> None:
    """Mirror the connect account's verified state onto our Partner row."""
    account_id = account.get("id")
    if not account_id:
        return

    capabilities = account.get("capabilities") or {}
    transfers_active = capabilities.get("transfers") == "active"
    charges_enabled = bool(account.get("charges_enabled"))
    payouts_enabled = bool(account.get("payouts_enabled"))
    is_active = transfers_active or (charges_enabled and payouts_enabled)

    try:
        partner = Partner.objects.get(stripe_account_id=account_id)
    except Partner.DoesNotExist:
        logger.info(
            "scm.webhook.account_updated unknown_account=%s",
            account_id,
        )
        return

    if partner.stripe_account_verified != is_active:
        partner.stripe_account_verified = is_active
        partner.save(update_fields=["stripe_account_verified"])
        logger.info(
            "scm.webhook.account_updated partner=%s verified=%s",
            partner.pk, is_active,
        )


def _on_transfer_created(transfer: dict) -> None:
    """Backfill our row with the transfer ID if it landed there a different way.

    Stripe re-fires this for every Transfer.create — usually we already
    stamped ``stripe_transfer_id`` synchronously in ``create_payout``,
    so this is a no-op. The exception is a transfer created out-of-band
    (e.g. via the Stripe dashboard) — we record it on the matching
    payout row if the metadata pointed to one.
    """
    transfer_id = transfer.get("id")
    metadata = transfer.get("metadata") or {}
    payout_id = metadata.get("scm_payout_id")
    if not (transfer_id and payout_id):
        return
    try:
        payout = Payout.objects.get(pk=int(payout_id))
    except (Payout.DoesNotExist, ValueError, TypeError):
        return
    if not payout.stripe_transfer_id:
        payout.stripe_transfer_id = transfer_id
        # Don't flip status from PENDING — let create_payout's atomic
        # block be the source of truth. Just attach the ID.
        payout.save(update_fields=["stripe_transfer_id"])
        logger.info(
            "scm.webhook.transfer_created linked payout=%s transfer=%s",
            payout.pk, transfer_id,
        )


def _on_transfer_reversed(transfer: dict) -> None:
    """Mark the matching payout REVERSED.

    Stripe fires this both when WE call ``Transfer.create_reversal``
    (our ``reverse_payout`` service already flipped the status; this
    is a confirmation) and when an out-of-band reversal happens (e.g.
    operator did it from the Stripe dashboard, or a refund cascaded).
    """
    transfer_id = transfer.get("id")
    if not transfer_id:
        return
    try:
        payout = Payout.objects.get(stripe_transfer_id=transfer_id)
    except Payout.DoesNotExist:
        logger.info(
            "scm.webhook.transfer_reversed unknown_transfer=%s",
            transfer_id,
        )
        return
    if payout.status != Payout.STATUS_REVERSED:
        payout.status = Payout.STATUS_REVERSED
        payout.save(update_fields=["status"])
        logger.info(
            "scm.webhook.transfer_reversed payout=%s",
            payout.pk,
        )
