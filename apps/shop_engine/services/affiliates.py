"""Affiliate services — create, magic-link, click tracking, attribution, payouts.

Hybrid auth (user-FK OR email-only) is handled here. The same service
functions accept either flavour — internally we branch on whether
``affiliate.user_id`` is set.

Click attribution
-----------------
``track_click(code, request)`` stamps a cookie + creates an
``AffiliateClick`` row. ``attribute_conversion(order, code)`` matches a
later order back to the affiliate by the code captured in the cookie
(snapshotted onto the ``Cart`` then the ``Order`` at checkout). If the
order has no affiliate_code, no conversion is recorded.

Magic-link login
----------------
For email-only affiliates: ``regenerate_magic_link`` produces a new
``magic_link_token`` and the view layer emails the affiliate a URL
``/affiliates/me/?token=<token>``. Tokens are long-lived by default
(``SHOP_MAGIC_LINK_TTL_HOURS``); rotate by calling this function again,
which invalidates the previous token.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from ..exceptions import (
    AffiliateInactive,
    AffiliateLoginInvalid,
)
from ..models import (
    Affiliate,
    AffiliateClick,
    AffiliateConversion,
    AffiliatePayout,
    Order,
    _new_magic_link_token,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Create / regenerate
# ---------------------------------------------------------------------------
@transaction.atomic
def create_affiliate(
    *,
    email: str,
    user=None,
    display_name: str = "",
    commission_bps: Optional[int] = None,
    flat_per_order_cents: int = 0,
    payout_method: str = Affiliate.PAYOUT_MANUAL,
    payout_details: Optional[dict] = None,
    status: str = Affiliate.STATUS_PENDING,
) -> Affiliate:
    """Create an affiliate row.

    If ``user`` is None, an email-only affiliate is created with a
    fresh magic-link token (so they can log in right away if the caller
    emails the token).
    """
    kwargs = {
        "email": email,
        "user": user,
        "display_name": display_name or "",
        "flat_per_order_cents": flat_per_order_cents,
        "payout_method": payout_method,
        "payout_details": payout_details or {},
        "status": status,
    }
    if commission_bps is not None:
        kwargs["commission_bps"] = commission_bps
    if user is None:
        kwargs["magic_link_token"] = _new_magic_link_token()
        kwargs["magic_link_sent_at"] = timezone.now()

    affiliate = Affiliate.objects.create(**kwargs)
    logger.info(
        "create_affiliate code=%s user=%s email=%s",
        affiliate.code, user.pk if user else "—", email,
    )
    return affiliate


def regenerate_magic_link(affiliate: Affiliate) -> str:
    """Rotate the magic-link token. Returns the new token.

    No-op for user-based affiliates (they don't need a magic link — they
    log in through the normal auth flow). Returns an empty string in
    that case.
    """
    if affiliate.is_user_based:
        logger.info("regenerate_magic_link skipped (user-based) code=%s", affiliate.code)
        return ""
    affiliate.magic_link_token = _new_magic_link_token()
    affiliate.magic_link_sent_at = timezone.now()
    affiliate.save(update_fields=["magic_link_token", "magic_link_sent_at", "updated_at"])
    return affiliate.magic_link_token


def resolve_affiliate_from_token(token: str) -> Affiliate:
    """Strict lookup by ``magic_link_token``. Validates active + non-expired."""
    if not token:
        raise AffiliateLoginInvalid("Missing magic-link token.")
    affiliate = Affiliate.objects.filter(magic_link_token=token).first()
    if affiliate is None:
        raise AffiliateLoginInvalid("Magic-link token not recognized.")

    ttl_hours = int(getattr(settings, "SHOP_MAGIC_LINK_TTL_HOURS", 24))
    if affiliate.magic_link_sent_at and ttl_hours > 0:
        if timezone.now() > affiliate.magic_link_sent_at + timedelta(hours=ttl_hours):
            raise AffiliateLoginInvalid("Magic-link token has expired.")

    if affiliate.status in {Affiliate.STATUS_BANNED, Affiliate.STATUS_PAUSED}:
        raise AffiliateInactive(f"Affiliate is {affiliate.status}.")
    return affiliate


# ---------------------------------------------------------------------------
# Click tracking
# ---------------------------------------------------------------------------
def track_click(*, code: str, request) -> Optional[AffiliateClick]:
    """Record an ``/r/<code>/`` landing hit, return the click row (or None).

    Caller (the landing view) handles setting the referral cookie on
    the response and the redirect — we just stamp the audit row.
    """
    affiliate = Affiliate.objects.filter(code__iexact=code).first()
    if affiliate is None:
        logger.info("track_click unknown code=%s", code)
        return None
    if affiliate.status != Affiliate.STATUS_ACTIVE:
        # Still record? No — a paused affiliate's clicks shouldn't
        # accumulate stats. Bouncing them keeps the data clean.
        logger.info("track_click ignored (status=%s) code=%s", affiliate.status, code)
        return None

    ip = _client_ip(request)
    ua = (request.META.get("HTTP_USER_AGENT", "") or "")[:500]
    referer = (request.META.get("HTTP_REFERER", "") or "")[:500]
    landing = request.build_absolute_uri()[:500] if hasattr(request, "build_absolute_uri") else ""
    if not request.session.session_key:
        try:
            request.session.create()
        except Exception:
            pass
    session_key = request.session.session_key or ""

    click = AffiliateClick.objects.create(
        affiliate=affiliate,
        ip=ip,
        user_agent=ua,
        referer=referer,
        landing_url=landing,
        session_key=session_key,
    )
    Affiliate.objects.filter(pk=affiliate.pk).update(total_clicks=F("total_clicks") + 1)
    logger.info("track_click code=%s cookie=%s", code, click.cookie_id)
    return click


def _client_ip(request) -> Optional[str]:
    """Best-effort client IP — respects X-Forwarded-For when set."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


# ---------------------------------------------------------------------------
# Conversion attribution
# ---------------------------------------------------------------------------
@transaction.atomic
def attribute_conversion(*, order: Order, code: str) -> Optional[AffiliateConversion]:
    """Create the ``AffiliateConversion`` row for a paid order.

    Idempotent on ``(affiliate, order)``. Snapshots ``commission_bps`` +
    ``flat_per_order_cents`` so future tweaks don't rewrite history.

    Returns the conversion or None if the affiliate code didn't resolve
    / wasn't active at order time.
    """
    if not code:
        return None
    affiliate = Affiliate.objects.filter(code__iexact=code, status=Affiliate.STATUS_ACTIVE).first()
    if affiliate is None:
        logger.info("attribute_conversion no active affiliate for code=%s", code)
        return None

    # Compute commission from snapshots
    gross = int(order.subtotal_cents)
    bps = int(affiliate.commission_bps)
    flat = int(affiliate.flat_per_order_cents)
    commission = (gross * bps) // 10_000 + flat

    conv, created = AffiliateConversion.objects.get_or_create(
        affiliate=affiliate,
        order=order,
        defaults={
            "gross_cents": gross,
            "commission_bps_applied": bps,
            "flat_per_order_cents_applied": flat,
            "commission_cents": commission,
            "status": AffiliateConversion.STATUS_APPROVED,
        },
    )
    if created:
        Affiliate.objects.filter(pk=affiliate.pk).update(
            total_conversions=F("total_conversions") + 1,
        )
        logger.info(
            "attribute_conversion code=%s order=%s commission=%d",
            code, order.order_number, commission,
        )
    return conv


# ---------------------------------------------------------------------------
# Payouts
# ---------------------------------------------------------------------------
@transaction.atomic
def generate_payout_batch(
    *,
    affiliate: Affiliate,
    period_start,
    period_end,
) -> Optional[AffiliatePayout]:
    """Aggregate every APPROVED conversion in the period into one payout row.

    Returns the new ``AffiliatePayout`` (or None if there are no
    eligible conversions in the period).

    Conversions are atomically linked to the payout (``conv.payout =
    payout``) so a second call with the same period doesn't re-aggregate
    the same rows.
    """
    convs = (
        AffiliateConversion.objects.select_for_update()
        .filter(
            affiliate=affiliate,
            status=AffiliateConversion.STATUS_APPROVED,
            payout__isnull=True,
            created_at__gte=period_start,
            created_at__lt=period_end,
        )
    )
    convs_list = list(convs)
    if not convs_list:
        return None

    gross_total = sum(int(c.gross_cents) for c in convs_list)
    commission_total = sum(int(c.commission_cents) for c in convs_list)

    payout = AffiliatePayout.objects.create(
        affiliate=affiliate,
        period_start=period_start,
        period_end=period_end,
        conversion_count=len(convs_list),
        gross_cents=gross_total,
        commission_cents=commission_total,
        fee_cents=0,
        net_cents=commission_total,
    )
    AffiliateConversion.objects.filter(
        pk__in=[c.pk for c in convs_list],
    ).update(payout=payout)
    logger.info(
        "generate_payout_batch affiliate=%s period=%s..%s count=%d net=%d",
        affiliate.code, period_start, period_end, len(convs_list), commission_total,
    )
    return payout


@transaction.atomic
def mark_payout_paid(
    payout: AffiliatePayout,
    *,
    external_payout_id: str = "",
    fee_cents: int = 0,
    paid_by=None,
    notes: str = "",
) -> AffiliatePayout:
    """Flip a payout to PAID + propagate to its conversions.

    The operator passes ``external_payout_id`` (PayPal batch ID, bank
    reference) and an optional ``fee_cents`` deduction. ``net_cents`` is
    recomputed.
    """
    if payout.status == AffiliatePayout.STATUS_PAID:
        return payout

    payout.status = AffiliatePayout.STATUS_PAID
    payout.external_payout_id = external_payout_id
    payout.fee_cents = int(fee_cents)
    payout.net_cents = max(int(payout.commission_cents) - int(fee_cents), 0)
    payout.paid_at = timezone.now()
    payout.paid_by = paid_by
    if notes:
        payout.notes = notes
    payout.save(update_fields=[
        "status", "external_payout_id", "fee_cents", "net_cents",
        "paid_at", "paid_by", "notes",
    ])

    # Update each linked conversion + the affiliate's denormalized counter.
    convs = AffiliateConversion.objects.filter(payout=payout)
    convs.update(status=AffiliateConversion.STATUS_PAID, paid_at=timezone.now())

    Affiliate.objects.filter(pk=payout.affiliate_id).update(
        total_paid_cents=F("total_paid_cents") + payout.net_cents,
    )
    logger.info(
        "mark_payout_paid payout=%s affiliate=%s net=%d external=%s",
        payout.pk, payout.affiliate.code, payout.net_cents, external_payout_id,
    )
    return payout


@transaction.atomic
def mark_payout_failed(payout: AffiliatePayout, *, notes: str = "") -> AffiliatePayout:
    """Flag a payout failed (so the operator can retry).

    Linked conversions are unlinked so they're picked up by the next
    ``generate_payout_batch`` call.
    """
    payout.status = AffiliatePayout.STATUS_FAILED
    if notes:
        payout.notes = (payout.notes + "\n" + notes) if payout.notes else notes
    payout.save(update_fields=["status", "notes"])
    AffiliateConversion.objects.filter(payout=payout).update(payout=None)
    return payout


# ---------------------------------------------------------------------------
# Dashboard helpers
# ---------------------------------------------------------------------------
def compute_pending_commissions(affiliate: Affiliate) -> dict:
    """Return ``{pending_cents, approved_cents, paid_cents, count}`` for the affiliate."""
    qs = AffiliateConversion.objects.filter(affiliate=affiliate)
    pending = qs.filter(status=AffiliateConversion.STATUS_PENDING)
    approved = qs.filter(status=AffiliateConversion.STATUS_APPROVED)
    paid = qs.filter(status=AffiliateConversion.STATUS_PAID)
    return {
        "pending_cents": sum(int(c.commission_cents) for c in pending),
        "approved_cents": sum(int(c.commission_cents) for c in approved),
        "paid_cents": sum(int(c.commission_cents) for c in paid),
        "count": qs.count(),
    }
