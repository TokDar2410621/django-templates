"""Pure-math tests for ``compute_payout``.

No I/O, no Stripe — just arithmetic. Fast, deterministic.
"""
from __future__ import annotations

import pytest

from stripe_connect_multivendor.models import PartnerProductShare
from stripe_connect_multivendor.services import compute_payout


@pytest.mark.django_db
def test_default_share_70_percent(partner):
    """7000 bps on $10 → partner $7, platform $3."""
    out = compute_payout(gross_cents=1000, partner=partner)
    assert out["gross_cents"] == 1000
    assert out["share_bps"] == 7000
    assert out["partner_amount_cents"] == 700
    assert out["platform_fee_cents"] == 300


@pytest.mark.django_db
def test_flat_fee_deducted_before_share(partner):
    """Cover $2 cost of goods, then 70/30 the markup."""
    partner.flat_per_order_cents = 200
    partner.save(update_fields=["flat_per_order_cents"])
    # gross=1000, net after flat=800, partner=800*0.7=560, platform=440
    out = compute_payout(gross_cents=1000, partner=partner)
    assert out["partner_amount_cents"] == 560
    assert out["platform_fee_cents"] == 440


@pytest.mark.django_db
def test_per_sku_override_wins_over_default(partner):
    PartnerProductShare.objects.create(
        partner=partner, external_product_id="special-sku", share_bps=5000,
    )
    out = compute_payout(
        gross_cents=2000,
        partner=partner,
        external_product_id="special-sku",
    )
    assert out["share_bps"] == 5000
    assert out["partner_amount_cents"] == 1000


@pytest.mark.django_db
def test_line_level_override_wins_over_sku(partner):
    PartnerProductShare.objects.create(
        partner=partner, external_product_id="special-sku", share_bps=5000,
    )
    out = compute_payout(
        gross_cents=2000,
        partner=partner,
        external_product_id="special-sku",
        share_bps_override=9000,  # promotional 90% rev share for this line
    )
    assert out["share_bps"] == 9000
    assert out["partner_amount_cents"] == 1800


@pytest.mark.django_db
def test_zero_gross_returns_zero(partner):
    out = compute_payout(gross_cents=0, partner=partner)
    assert out == {
        "gross_cents": 0,
        "share_bps": 7000,
        "partner_amount_cents": 0,
        "platform_fee_cents": 0,
    }


@pytest.mark.django_db
def test_flat_larger_than_gross_clamps_partner_to_zero(partner):
    """If COGS > selling price, partner gets nothing (platform absorbs it)."""
    partner.flat_per_order_cents = 5000
    partner.save(update_fields=["flat_per_order_cents"])
    out = compute_payout(gross_cents=1000, partner=partner)
    assert out["partner_amount_cents"] == 0
    assert out["platform_fee_cents"] == 1000


@pytest.mark.django_db
def test_negative_gross_rejected(partner):
    with pytest.raises(ValueError):
        compute_payout(gross_cents=-1, partner=partner)


@pytest.mark.django_db
def test_share_bps_out_of_range_rejected(partner):
    with pytest.raises(ValueError):
        compute_payout(
            gross_cents=1000, partner=partner, share_bps_override=20_000,
        )


@pytest.mark.django_db
def test_full_share_partner_keeps_all(partner):
    """10000 bps = 100% revenue share → platform fee 0."""
    out = compute_payout(
        gross_cents=1500, partner=partner, share_bps_override=10_000,
    )
    assert out["partner_amount_cents"] == 1500
    assert out["platform_fee_cents"] == 0


@pytest.mark.django_db
def test_rounding_uses_floor(partner):
    """7000 bps × 333 cents = 233.1 — partner gets 233 (floored)."""
    out = compute_payout(gross_cents=333, partner=partner)
    assert out["partner_amount_cents"] == 233
    assert out["platform_fee_cents"] == 100
