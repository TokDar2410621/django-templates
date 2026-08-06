"""Signal receivers.

Currently wired:

- ``order_paid`` — after an Order transitions to PAID, walk its items
  and refresh every matching review's ``is_verified_purchase`` flag.
  This handles the case where a user posted a review BEFORE buying the
  product and we want the flag to flip the moment the purchase clears.

We don't ship a custom Django signal for ``order_paid`` — we just hook
``Order.post_save`` and detect the status transition by comparing old
vs new. That keeps the surface area small and doesn't force services
that mutate an Order to remember to fire a separate signal.
"""
from __future__ import annotations

import logging

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import Order

logger = logging.getLogger(__name__)


# We stash the previous status on the instance during pre_save so
# post_save can detect a transition without an extra DB roundtrip.
@receiver(pre_save, sender=Order)
def _stash_previous_status(sender, instance: Order, **kwargs) -> None:
    if not instance.pk:
        instance._previous_status = None  # type: ignore[attr-defined]
        return
    prev = Order.objects.filter(pk=instance.pk).only("status").first()
    instance._previous_status = prev.status if prev else None  # type: ignore[attr-defined]


@receiver(post_save, sender=Order)
def _refresh_verified_reviews_on_paid(sender, instance: Order, created: bool, **kwargs) -> None:
    previous = getattr(instance, "_previous_status", None)
    if previous == instance.status:
        return
    if instance.status not in Order.PAID_STATUSES:
        return
    # Only fire on the FIRST transition into a paid-like status.
    if previous in Order.PAID_STATUSES:
        return

    user = instance.user
    if user is None:
        return

    # Lazy import to avoid circular at app-ready time.
    from .services.reviews import refresh_verified_flag_for_user_product

    for item in instance.items.all():
        if item.product_id is None:
            continue
        try:
            refresh_verified_flag_for_user_product(user=user, product=item.product)
        except Exception:
            logger.exception(
                "Could not refresh verified flag for order=%s product=%s",
                instance.order_number, item.product_id,
            )
