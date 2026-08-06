"""Read-only queries for activation batches + codes.

Kept separate from ``services.py`` so DRF views and admin code can do
lookups without importing the transactional write paths.
"""
from __future__ import annotations

from typing import Iterable, Optional

from django.db.models import Count, Q

from .models import ActivationBatch, ActivationCode, ClaimStatus


def get_by_slug(slug: str) -> Optional[ActivationCode]:
    """Look up an :class:`ActivationCode` by its public ``qr_slug``.

    Returns the row regardless of consumption state — callers decide what
    to surface. Use ``select_related("batch")`` is included so the caller
    can read ``claim_mode`` without an extra query.
    """
    if not slug:
        return None
    return (
        ActivationCode.objects
        .select_related("batch")
        .filter(qr_slug=slug.strip().lower())
        .first()
    )


def get_by_code(activation_code: str) -> Optional[ActivationCode]:
    """Look up an :class:`ActivationCode` by its printed ``activation_code``.

    Only useful for support / customer service flows — the regular claim
    flow always looks up by ``(slug, code)`` together.
    """
    code = (activation_code or "").strip()
    if not code:
        return None
    return (
        ActivationCode.objects
        .select_related("batch")
        .filter(activation_code=code)
        .first()
    )


def batch_stats(batch: ActivationBatch | int) -> dict:
    """Return per-status counts for a batch.

    Shape::

        {
            "size":         1000,
            "consumed":     312,
            "remaining":    688,
            "provisional":  20,
            "confirmed":    290,
            "disputed":     2,
        }

    Single aggregate query (no N+1). Accepts either a model instance or
    a pk for caller convenience.
    """
    batch_id = batch.pk if isinstance(batch, ActivationBatch) else int(batch)
    qs = ActivationCode.objects.filter(batch_id=batch_id)
    agg = qs.aggregate(
        size=Count("id"),
        consumed=Count("id", filter=Q(consumed_at__isnull=False)),
        provisional=Count("id", filter=Q(claim_status=ClaimStatus.PROVISIONAL)),
        confirmed=Count(
            "id",
            filter=Q(
                claim_status=ClaimStatus.CONFIRMED,
                consumed_at__isnull=False,
            ),
        ),
        disputed=Count("id", filter=Q(claim_status=ClaimStatus.DISPUTED)),
    )
    agg["remaining"] = max(0, (agg["size"] or 0) - (agg["consumed"] or 0))
    return agg


def unclaimed_count(batch: ActivationBatch | int) -> int:
    """How many codes in this batch are still available to claim."""
    batch_id = batch.pk if isinstance(batch, ActivationBatch) else int(batch)
    return ActivationCode.objects.filter(
        batch_id=batch_id, consumed_at__isnull=True,
    ).count()


def codes_in_batch(batch: ActivationBatch | int) -> Iterable[ActivationCode]:
    """All codes belonging to a batch, in stable order. Audit-friendly."""
    batch_id = batch.pk if isinstance(batch, ActivationBatch) else int(batch)
    return (
        ActivationCode.objects
        .filter(batch_id=batch_id)
        .order_by("qr_slug")
    )
