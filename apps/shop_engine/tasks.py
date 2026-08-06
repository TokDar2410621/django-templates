"""Celery tasks — scheduled syncs + dispatches + cart sweeps.

If your project doesn't use Celery, you can still call these as plain
functions from a management command — the ``@shared_task`` decorator
falls through cleanly.

Recommended Celery beat schedule lives in ``SETTINGS.md``.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Optional

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


# Celery is optional — if unavailable, ``shared_task`` becomes a passthrough.
try:
    from celery import shared_task
except ImportError:  # pragma: no cover - optional dep
    def shared_task(*args, **kwargs):
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]

        def _wrap(fn):
            return fn
        return _wrap


# ---------------------------------------------------------------------------
# Catalogue sync
# ---------------------------------------------------------------------------
@shared_task(bind=True, ignore_result=True)
def sync_catalog_from_provider(self, provider_name: Optional[str] = None, *, force: bool = False) -> dict:
    """Beat-scheduled: pull the upstream catalogue into local rows."""
    from .services.catalog import sync_from_provider

    result = sync_from_provider(provider_name=provider_name, force=force)
    return {
        "provider": provider_name or "default",
        "products_created": result.products_created,
        "products_updated": result.products_updated,
        "variants_created": result.variants_created,
        "variants_updated": result.variants_updated,
        "errors": result.errors,
    }


# ---------------------------------------------------------------------------
# Fulfillment dispatch
# ---------------------------------------------------------------------------
@shared_task(bind=True, ignore_result=True)
def dispatch_paid_orders(self) -> dict:
    """Beat-scheduled (every 5 min): dispatch paid+local orders to provider."""
    from .models import Order
    from .services.fulfillment import dispatch_to_provider

    qs = (
        Order.objects
        .filter(status=Order.STATUS_PAID)
        .order_by("paid_at")[:100]
    )
    dispatched = 0
    errors: list[str] = []
    for order in qs:
        try:
            dispatch_to_provider(order)
            dispatched += 1
        except Exception as exc:
            logger.exception("dispatch_paid_orders failed order=%s", order.order_number)
            errors.append(f"{order.order_number}: {exc}")
    return {"dispatched": dispatched, "errors": errors}


@shared_task(bind=True, ignore_result=True)
def poll_provider_order_status(self) -> dict:
    """Beat-scheduled (hourly): poll provider for ``fulfilling`` orders."""
    from .models import Order, ProviderSyncLog
    from .providers import get_fulfillment_provider
    from .services.fulfillment import mark_shipped, mark_delivered

    provider = get_fulfillment_provider()
    qs = Order.objects.filter(status=Order.STATUS_FULFILLING)[:200]
    updates: list[str] = []
    for order in qs:
        external = (order.provider_metadata or {}).get("external_order_id")
        if not external:
            continue
        try:
            status = provider.get_order_status(external)
        except NotImplementedError:
            ProviderSyncLog.objects.create(
                provider=provider.name,
                action="get_order_status",
                external_id=external,
                status=ProviderSyncLog.STATUS_ERROR,
                error_message="Provider stub — not implemented.",
            )
            continue
        except Exception as exc:
            logger.exception("poll_provider_order_status failed order=%s", order.order_number)
            ProviderSyncLog.objects.create(
                provider=provider.name,
                action="get_order_status",
                external_id=external,
                status=ProviderSyncLog.STATUS_ERROR,
                error_message=str(exc),
            )
            continue

        # Provider-status semantics are per-provider. Project authors
        # should map ``status.status`` to our Order statuses in the
        # provider implementation — here we only handle the two
        # universal terminal cases.
        s = (status.status or "").lower()
        if s in {"shipped", "in_transit"}:
            tracking = None
            try:
                tracking = provider.get_tracking(external)
            except NotImplementedError:
                pass
            mark_shipped(
                order,
                tracking_number=getattr(tracking, "tracking_number", "") if tracking else "",
                tracking_url=getattr(tracking, "tracking_url", "") if tracking else "",
                carrier=getattr(tracking, "carrier", "") if tracking else "",
            )
            updates.append(f"{order.order_number}→shipped")
        elif s in {"delivered"}:
            mark_delivered(order)
            updates.append(f"{order.order_number}→delivered")
    return {"updates": updates}


# ---------------------------------------------------------------------------
# Cart janitor
# ---------------------------------------------------------------------------
@shared_task(bind=True, ignore_result=True)
def expire_old_carts(self) -> dict:
    """Daily: delete anonymous carts older than ``SHOP_CART_EXPIRY_DAYS``."""
    from .models import Cart

    days = int(getattr(settings, "SHOP_CART_EXPIRY_DAYS", 30))
    cutoff = timezone.now() - timedelta(days=days)
    qs = Cart.objects.filter(user__isnull=True, updated_at__lt=cutoff)
    count = qs.count()
    qs.delete()
    logger.info("expire_old_carts deleted=%d cutoff=%s", count, cutoff)
    return {"deleted": count}


# ---------------------------------------------------------------------------
# Affiliate notifications (hook only — projects bring their own email)
# ---------------------------------------------------------------------------
@shared_task(bind=True, ignore_result=True)
def send_affiliate_payout_notification(self, payout_id: int) -> dict:
    """Fire a signal/log entry — projects override to send a real email.

    The template doesn't ship an email backend (that's the
    ``notifications-multichannel`` template's job). Hook into this task
    by overriding it in your project::

        @shared_task(name="shop_engine.tasks.send_affiliate_payout_notification")
        def send_affiliate_payout_notification(payout_id: int):
            from shop_engine.models import AffiliatePayout
            payout = AffiliatePayout.objects.select_related("affiliate").get(pk=payout_id)
            notifications_multichannel.send_email(
                to=payout.affiliate.email,
                role="orders",
                subject=f"Payout sent: {payout.net_cents / 100:.2f}",
                html=render_to_string("emails/affiliate_payout.html", {"payout": payout}),
            )
    """
    from .models import AffiliatePayout

    payout = AffiliatePayout.objects.filter(pk=payout_id).first()
    if payout is None:
        return {"sent": False, "reason": "payout not found"}
    logger.info(
        "send_affiliate_payout_notification payout=%s affiliate=%s "
        "(override this task to send a real email)",
        payout.pk, payout.affiliate.code,
    )
    return {"sent": True, "stub": True}
