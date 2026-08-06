"""I/O tests for ``create_payout`` / ``bulk_payout_for_order`` / ``reverse_payout``.

Stripe SDK is stubbed in conftest. We assert on what we WOULD have
sent (idempotency_key, amount, destination) and on the resulting
ledger row state.
"""
from __future__ import annotations

import pytest

from stripe_connect_multivendor.models import Payout
from stripe_connect_multivendor.services import (
    PartnerNotPayable,
    bulk_payout_for_order,
    create_payout,
    reverse_payout,
)


@pytest.mark.django_db
def test_create_payout_happy_path(stub_stripe, partner):
    payout = create_payout(
        partner=partner,
        external_order_id="ord_1",
        external_order_item_id="item_1",
        gross_cents=1000,
        currency="CAD",
    )
    assert payout.status == Payout.STATUS_PAID
    assert payout.partner_amount_cents == 700
    assert payout.platform_fee_cents == 300
    assert payout.stripe_transfer_id == "tr_test_123"
    assert payout.paid_at is not None

    # Stripe call inspection
    stub_stripe.Transfer.create.assert_called_once()
    kwargs = stub_stripe.Transfer.create.call_args.kwargs
    assert kwargs["amount"] == 700
    assert kwargs["currency"] == "cad"          # lowercased for Stripe
    assert kwargs["destination"] == "acct_alice"
    assert kwargs["idempotency_key"] == f"scm_payout_{payout.pk}"
    assert kwargs["transfer_group"] == "order_ord_1"


@pytest.mark.django_db
def test_create_payout_is_idempotent(stub_stripe, partner):
    p1 = create_payout(
        partner=partner,
        external_order_id="ord_1",
        external_order_item_id="item_1",
        gross_cents=1000,
    )
    p2 = create_payout(
        partner=partner,
        external_order_id="ord_1",
        external_order_item_id="item_1",
        gross_cents=1000,
    )
    assert p1.pk == p2.pk
    # PAID row is not re-fired.
    stub_stripe.Transfer.create.assert_called_once()


@pytest.mark.django_db
def test_create_payout_records_stripe_error(stub_stripe, partner):
    stub_stripe.Transfer.create.side_effect = stub_stripe.error.StripeError(
        "destination account requires transfers capability"
    )
    payout = create_payout(
        partner=partner,
        external_order_id="ord_1",
        external_order_item_id="item_1",
        gross_cents=1000,
    )
    assert payout.status == Payout.STATUS_FAILED
    assert "transfers capability" in payout.error
    assert not payout.stripe_transfer_id


@pytest.mark.django_db
def test_create_payout_retry_after_failure(stub_stripe, partner):
    stub_stripe.Transfer.create.side_effect = stub_stripe.error.StripeError("nope")
    failed = create_payout(
        partner=partner,
        external_order_id="ord_1",
        external_order_item_id="item_1",
        gross_cents=1000,
    )
    assert failed.status == Payout.STATUS_FAILED

    # Stripe recovered; retry the same line.
    stub_stripe.Transfer.create.side_effect = None
    retried = create_payout(
        partner=partner,
        external_order_id="ord_1",
        external_order_item_id="item_1",
        gross_cents=1000,
    )
    assert retried.pk == failed.pk           # same row, updated in place
    assert retried.status == Payout.STATUS_PAID
    assert retried.error == ""


@pytest.mark.django_db
def test_unverified_partner_raises_not_payable(stub_stripe, unverified_partner):
    with pytest.raises(PartnerNotPayable):
        create_payout(
            partner=unverified_partner,
            external_order_id="ord_1",
            external_order_item_id="item_1",
            gross_cents=1000,
        )
    stub_stripe.Transfer.create.assert_not_called()
    # No row was committed (the transaction rolled back via the raise
    # before the Stripe call — see source). The atomic block bails out.


@pytest.mark.django_db
def test_zero_amount_payout_marked_paid_without_stripe(stub_stripe, partner):
    """A line that nets $0 to the partner shouldn't bother Stripe."""
    partner.flat_per_order_cents = 1000
    partner.save(update_fields=["flat_per_order_cents"])
    payout = create_payout(
        partner=partner,
        external_order_id="ord_1",
        external_order_item_id="item_1",
        gross_cents=500,           # less than the flat → partner gets 0
    )
    assert payout.partner_amount_cents == 0
    assert payout.status == Payout.STATUS_PAID
    stub_stripe.Transfer.create.assert_not_called()


@pytest.mark.django_db
def test_bulk_payout_for_order_creates_one_row_per_line(
    stub_stripe, partner, unverified_partner,
):
    results = bulk_payout_for_order(
        external_order_id="ord_42",
        line_items=[
            {
                "external_order_item_id": "item_a",
                "gross_cents": 1000,
                "partner_id": partner.pk,
            },
            {
                "external_order_item_id": "item_b",
                "gross_cents": 2000,
                "partner_id": unverified_partner.pk,
            },
        ],
    )
    assert len(results) == 2
    by_item = {r.external_order_item_id: r for r in results}
    assert by_item["item_a"].status == Payout.STATUS_PAID
    # Unverified partner → FAILED row recorded with the not-payable reason
    assert by_item["item_b"].status == Payout.STATUS_FAILED
    assert "cannot receive" in by_item["item_b"].error.lower()


@pytest.mark.django_db
def test_bulk_skips_unknown_partner(stub_stripe, partner):
    results = bulk_payout_for_order(
        external_order_id="ord_42",
        line_items=[
            {
                "external_order_item_id": "item_a",
                "gross_cents": 1000,
                "partner_id": partner.pk,
            },
            {
                "external_order_item_id": "item_b",
                "gross_cents": 2000,
                "partner_id": 99999,  # nonexistent
            },
        ],
    )
    assert len(results) == 1
    assert results[0].external_order_item_id == "item_a"


@pytest.mark.django_db
def test_reverse_payout_marks_row_reversed(stub_stripe, partner):
    payout = create_payout(
        partner=partner,
        external_order_id="ord_1",
        external_order_item_id="item_1",
        gross_cents=1000,
    )
    assert payout.status == Payout.STATUS_PAID
    reversed_row = reverse_payout(payout, reason="customer_refund")
    assert reversed_row.status == Payout.STATUS_REVERSED
    stub_stripe.Transfer.create_reversal.assert_called_once()
    kwargs = stub_stripe.Transfer.create_reversal.call_args.kwargs
    assert kwargs["idempotency_key"] == f"scm_payout_{payout.pk}_reversal"


@pytest.mark.django_db
def test_reverse_payout_refuses_unpaid_row(stub_stripe, partner):
    # Force a PENDING row by mocking the transfer call to raise so the
    # row lands in FAILED, then bring it back to PENDING by hand.
    stub_stripe.Transfer.create.side_effect = stub_stripe.error.StripeError("x")
    payout = create_payout(
        partner=partner,
        external_order_id="ord_1",
        external_order_item_id="item_1",
        gross_cents=1000,
    )
    assert payout.status == Payout.STATUS_FAILED
    with pytest.raises(ValueError):
        reverse_payout(payout)
