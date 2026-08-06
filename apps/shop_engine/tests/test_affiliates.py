"""Affiliate tests — create, magic-link, click, conversion, payouts."""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from shop_engine.exceptions import AffiliateInactive, AffiliateLoginInvalid
from shop_engine.models import (
    Affiliate,
    AffiliateClick,
    AffiliateConversion,
    AffiliatePayout,
    Order,
)
from shop_engine.services import affiliates as aff_svc


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_create_affiliate_user_based_no_magic_link(other_user):
    aff = aff_svc.create_affiliate(
        email=other_user.email, user=other_user, commission_bps=1500,
    )
    assert aff.is_user_based
    assert aff.magic_link_token == ""


@pytest.mark.django_db
def test_create_affiliate_email_only_gets_token(db):
    aff = aff_svc.create_affiliate(email="external@example.com")
    assert aff.is_email_only
    assert aff.magic_link_token  # populated


@pytest.mark.django_db
def test_create_affiliate_unique_code(db):
    a1 = aff_svc.create_affiliate(email="a@x.com")
    a2 = aff_svc.create_affiliate(email="b@x.com")
    assert a1.code != a2.code


# ---------------------------------------------------------------------------
# Magic link
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_regenerate_magic_link_rotates(affiliate_email_only):
    old = affiliate_email_only.magic_link_token
    new = aff_svc.regenerate_magic_link(affiliate_email_only)
    assert new and new != old


@pytest.mark.django_db
def test_regenerate_magic_link_skipped_for_user_based(affiliate_user_based):
    new = aff_svc.regenerate_magic_link(affiliate_user_based)
    assert new == ""


@pytest.mark.django_db
def test_resolve_affiliate_from_token_ok(affiliate_email_only):
    resolved = aff_svc.resolve_affiliate_from_token(affiliate_email_only.magic_link_token)
    assert resolved.pk == affiliate_email_only.pk


@pytest.mark.django_db
def test_resolve_affiliate_from_token_invalid(db):
    with pytest.raises(AffiliateLoginInvalid):
        aff_svc.resolve_affiliate_from_token("not-a-real-token")


@pytest.mark.django_db
def test_resolve_affiliate_from_token_expired(settings, affiliate_email_only):
    settings.SHOP_MAGIC_LINK_TTL_HOURS = 1
    affiliate_email_only.magic_link_sent_at = timezone.now() - timedelta(hours=2)
    affiliate_email_only.save()
    with pytest.raises(AffiliateLoginInvalid):
        aff_svc.resolve_affiliate_from_token(affiliate_email_only.magic_link_token)


@pytest.mark.django_db
def test_resolve_affiliate_paused_raises(affiliate_email_only):
    affiliate_email_only.status = Affiliate.STATUS_PAUSED
    affiliate_email_only.save()
    with pytest.raises(AffiliateInactive):
        aff_svc.resolve_affiliate_from_token(affiliate_email_only.magic_link_token)


# ---------------------------------------------------------------------------
# Click tracking
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_track_click_records_row(affiliate_user_based, rf):
    request = rf.get("/r/" + affiliate_user_based.code + "/")
    from django.contrib.sessions.middleware import SessionMiddleware

    sm = SessionMiddleware(lambda r: None)
    sm.process_request(request)
    request.session.save()

    click = aff_svc.track_click(code=affiliate_user_based.code, request=request)
    assert click is not None
    assert click.affiliate_id == affiliate_user_based.pk
    affiliate_user_based.refresh_from_db()
    assert affiliate_user_based.total_clicks == 1


@pytest.mark.django_db
def test_track_click_unknown_code_returns_none(rf):
    request = rf.get("/r/NOPE/")
    from django.contrib.sessions.middleware import SessionMiddleware

    sm = SessionMiddleware(lambda r: None)
    sm.process_request(request)

    click = aff_svc.track_click(code="NOPE", request=request)
    assert click is None


# ---------------------------------------------------------------------------
# Conversion attribution
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_attribute_conversion_creates_row(affiliate_user_based, user):
    order = Order.objects.create(
        user=user,
        email=user.email,
        status=Order.STATUS_PAID,
        subtotal_cents=10000,
        total_cents=10000,
        affiliate_code=affiliate_user_based.code,
    )
    conv = aff_svc.attribute_conversion(order=order, code=affiliate_user_based.code)
    assert conv is not None
    # 10000 * 1500/10000 = 1500 (15%), no flat
    assert conv.commission_cents == 1500
    assert conv.status == AffiliateConversion.STATUS_APPROVED


@pytest.mark.django_db
def test_attribute_conversion_with_flat(affiliate_email_only, user):
    order = Order.objects.create(
        user=user, email=user.email, status=Order.STATUS_PAID,
        subtotal_cents=10000, total_cents=10000,
        affiliate_code=affiliate_email_only.code,
    )
    conv = aff_svc.attribute_conversion(order=order, code=affiliate_email_only.code)
    # 10000 * 2000/10000 = 2000 + flat 500 = 2500
    assert conv.commission_cents == 2500


@pytest.mark.django_db
def test_attribute_conversion_idempotent(affiliate_user_based, user):
    order = Order.objects.create(
        user=user, email=user.email, status=Order.STATUS_PAID,
        subtotal_cents=10000, total_cents=10000,
        affiliate_code=affiliate_user_based.code,
    )
    aff_svc.attribute_conversion(order=order, code=affiliate_user_based.code)
    aff_svc.attribute_conversion(order=order, code=affiliate_user_based.code)
    assert AffiliateConversion.objects.filter(order=order).count() == 1


@pytest.mark.django_db
def test_attribute_conversion_unknown_code_no_op(user):
    order = Order.objects.create(
        user=user, email=user.email, status=Order.STATUS_PAID,
        subtotal_cents=10000, total_cents=10000, affiliate_code="GHOST",
    )
    conv = aff_svc.attribute_conversion(order=order, code="GHOST")
    assert conv is None


# ---------------------------------------------------------------------------
# Payouts
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_generate_payout_batch_aggregates(affiliate_user_based, user):
    now = timezone.now()
    for i in range(3):
        order = Order.objects.create(
            user=user, email=user.email, status=Order.STATUS_PAID,
            subtotal_cents=10000, total_cents=10000,
            affiliate_code=affiliate_user_based.code,
        )
        aff_svc.attribute_conversion(order=order, code=affiliate_user_based.code)

    payout = aff_svc.generate_payout_batch(
        affiliate=affiliate_user_based,
        period_start=now - timedelta(hours=1),
        period_end=now + timedelta(hours=1),
    )
    assert payout is not None
    assert payout.conversion_count == 3
    assert payout.commission_cents == 3 * 1500


@pytest.mark.django_db
def test_generate_payout_batch_no_conversions_returns_none(affiliate_user_based):
    now = timezone.now()
    payout = aff_svc.generate_payout_batch(
        affiliate=affiliate_user_based,
        period_start=now - timedelta(hours=1),
        period_end=now + timedelta(hours=1),
    )
    assert payout is None


@pytest.mark.django_db
def test_generate_payout_batch_doesnt_double_aggregate(affiliate_user_based, user):
    now = timezone.now()
    order = Order.objects.create(
        user=user, email=user.email, status=Order.STATUS_PAID,
        subtotal_cents=10000, total_cents=10000,
        affiliate_code=affiliate_user_based.code,
    )
    aff_svc.attribute_conversion(order=order, code=affiliate_user_based.code)

    p1 = aff_svc.generate_payout_batch(
        affiliate=affiliate_user_based,
        period_start=now - timedelta(hours=1),
        period_end=now + timedelta(hours=1),
    )
    p2 = aff_svc.generate_payout_batch(
        affiliate=affiliate_user_based,
        period_start=now - timedelta(hours=1),
        period_end=now + timedelta(hours=1),
    )
    assert p1 is not None
    assert p2 is None  # nothing left to aggregate


@pytest.mark.django_db
def test_mark_payout_paid_updates_conversions(affiliate_user_based, user):
    now = timezone.now()
    order = Order.objects.create(
        user=user, email=user.email, status=Order.STATUS_PAID,
        subtotal_cents=10000, total_cents=10000,
        affiliate_code=affiliate_user_based.code,
    )
    aff_svc.attribute_conversion(order=order, code=affiliate_user_based.code)
    payout = aff_svc.generate_payout_batch(
        affiliate=affiliate_user_based,
        period_start=now - timedelta(hours=1),
        period_end=now + timedelta(hours=1),
    )
    aff_svc.mark_payout_paid(payout, external_payout_id="pp_batch_1")
    payout.refresh_from_db()
    assert payout.status == AffiliatePayout.STATUS_PAID
    assert payout.external_payout_id == "pp_batch_1"

    conv = AffiliateConversion.objects.get(order=order)
    assert conv.status == AffiliateConversion.STATUS_PAID
