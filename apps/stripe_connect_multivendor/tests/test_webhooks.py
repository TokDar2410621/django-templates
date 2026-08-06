"""Webhook router tests.

We exercise ``dispatch_event`` directly (bypassing signature
verification, which is Stripe SDK territory).
"""
from __future__ import annotations

import pytest

from stripe_connect_multivendor.models import Payout
from stripe_connect_multivendor.services import create_payout
from stripe_connect_multivendor.webhooks import dispatch_event


@pytest.mark.django_db
def test_account_updated_marks_partner_verified(unverified_partner):
    unverified_partner.stripe_account_id = "acct_bob"
    unverified_partner.save(update_fields=["stripe_account_id"])
    assert unverified_partner.stripe_account_verified is False

    handled = dispatch_event({
        "type": "account.updated",
        "data": {"object": {
            "id": "acct_bob",
            "capabilities": {"transfers": "active"},
            "charges_enabled": True,
            "payouts_enabled": True,
        }},
    })

    assert handled == "account.updated"
    unverified_partner.refresh_from_db()
    assert unverified_partner.stripe_account_verified is True


@pytest.mark.django_db
def test_account_updated_unknown_account_is_noop(unverified_partner):
    handled = dispatch_event({
        "type": "account.updated",
        "data": {"object": {
            "id": "acct_unknown",
            "capabilities": {"transfers": "active"},
        }},
    })
    assert handled == "account.updated"  # routed, just no-op
    unverified_partner.refresh_from_db()
    assert unverified_partner.stripe_account_verified is False


@pytest.mark.django_db
def test_transfer_created_links_id_when_missing(partner, stub_stripe):
    # Create a payout but simulate the stripe_transfer_id being absent
    # (as if the create call was async). We strip it from the row.
    payout = create_payout(
        partner=partner,
        external_order_id="ord_1",
        external_order_item_id="item_1",
        gross_cents=1000,
    )
    payout.stripe_transfer_id = ""
    payout.save(update_fields=["stripe_transfer_id"])

    dispatch_event({
        "type": "transfer.created",
        "data": {"object": {
            "id": "tr_late",
            "metadata": {"scm_payout_id": str(payout.pk)},
        }},
    })

    payout.refresh_from_db()
    assert payout.stripe_transfer_id == "tr_late"


@pytest.mark.django_db
def test_transfer_reversed_flips_status(partner, stub_stripe):
    payout = create_payout(
        partner=partner,
        external_order_id="ord_1",
        external_order_item_id="item_1",
        gross_cents=1000,
    )
    assert payout.status == Payout.STATUS_PAID

    dispatch_event({
        "type": "transfer.reversed",
        "data": {"object": {"id": payout.stripe_transfer_id}},
    })

    payout.refresh_from_db()
    assert payout.status == Payout.STATUS_REVERSED


@pytest.mark.django_db
def test_unknown_event_type_returns_none():
    result = dispatch_event({"type": "charge.refunded", "data": {"object": {}}})
    assert result is None
