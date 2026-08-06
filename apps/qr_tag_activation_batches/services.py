"""Activation services — batch generation, claim, dispute resolution.

Kept out of views.py so the admin actions and Celery tasks can call these
directly without going through a DRF view.

Public functions:
    - :func:`generate_batch`          create N codes atomically
    - :func:`claim_code`              redeem a CODE-mode tag
    - :func:`photo_claim`             redeem (or dispute) a PHOTO-mode tag
    - :func:`mark_disputed`           manually flag a code as DISPUTED
    - :func:`confirm_provisional`     promote PROVISIONAL → CONFIRMED/DISPUTED
                                      after the window closes (Celery)
    - :func:`bulk_export_csv`         partner-ready CSV of a batch
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import timedelta
from typing import Iterable, Optional

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction
from django.utils import timezone

from .models import (
    ActivationBatch,
    ActivationCode,
    ClaimMode,
    ClaimStatus,
    OwnershipDispute,
    _provisional_hours,
)
from .utils import generate_activation_code, generate_qr_slug

logger = logging.getLogger(__name__)


def _max_batch_size() -> int:
    return int(getattr(settings, "ACTIVATION_BATCH_MAX_SIZE", 10000))


# ---------------------------------------------------------------------------
# Exceptions — surfaced to view layer, mapped to HTTP codes there.
# ---------------------------------------------------------------------------
class BatchSizeError(ValueError):
    """Requested size is <= 0 or > ACTIVATION_BATCH_MAX_SIZE."""


class InvalidActivationError(Exception):
    """qr_slug + activation_code don't match any batch code."""


class AlreadyConsumedError(Exception):
    """Tried to redeem a code that's already been claimed."""


class WrongClaimModeError(Exception):
    """Photo-claim hit a CODE batch or vice versa."""


class AlreadyDisputedError(Exception):
    """Same user filing a second dispute on the same code."""


# ---------------------------------------------------------------------------
# Batch generation
# ---------------------------------------------------------------------------
def _slug_taken(slug: str) -> bool:
    """Check uniqueness against the activation table.

    If the caller has a parallel "live" slug column on its own model, it
    should also check that column — pass an extra predicate via the
    :setting:`ACTIVATION_EXTRA_SLUG_GUARD` callable (optional).
    """
    if ActivationCode.objects.filter(qr_slug=slug).exists():
        return True
    guard = getattr(settings, "ACTIVATION_EXTRA_SLUG_GUARD", None)
    if callable(guard) and guard(slug):
        return True
    return False


@transaction.atomic
def generate_batch(
    *,
    size: int,
    kind: str,
    tag_format: str,
    claim_mode: str = ClaimMode.CODE,
    partner_label: str = "",
    notes: str = "",
    created_by=None,
) -> ActivationBatch:
    """Create a batch + N codes inside a single transaction.

    Bulk-inserts the codes so a batch of 5000 doesn't fire 5000 SQL
    INSERTs. Slug collisions are rare in the 36^8 keyspace but we re-roll
    if one slips through.

    When ``claim_mode == ClaimMode.PHOTO``, no per-tag activation_code
    is generated — the field stays blank and the partial unique index on
    (batch, activation_code) doesn't fire.

    Raises:
        BatchSizeError: ``size`` out of range
    """
    max_size = _max_batch_size()
    if size <= 0 or size > max_size:
        raise BatchSizeError(f"size must be between 1 and {max_size}.")

    batch = ActivationBatch.objects.create(
        kind=kind,
        tag_format=tag_format,
        claim_mode=claim_mode,
        size=size,
        partner_label=partner_label,
        notes=notes,
        created_by=created_by,
    )

    seen_slugs: set[str] = set()
    seen_codes_in_batch: set[str] = set()
    rows: list[ActivationCode] = []
    for _ in range(size):
        # qr_slug — unique across all ActivationCode rows AND optionally
        # against the caller's extra slug-guard predicate.
        for _ in range(20):
            slug = generate_qr_slug()
            if slug not in seen_slugs and not _slug_taken(slug):
                seen_slugs.add(slug)
                break
        else:  # pragma: no cover - extremely unlikely
            raise RuntimeError("Could not allocate a unique qr_slug.")

        if claim_mode == ClaimMode.CODE:
            for _ in range(20):
                code = generate_activation_code()
                if code not in seen_codes_in_batch:
                    seen_codes_in_batch.add(code)
                    break
            else:  # pragma: no cover
                raise RuntimeError(
                    "Could not allocate a unique activation_code in this batch."
                )
        else:
            code = ""  # PHOTO mode — no per-tag code printed

        rows.append(
            ActivationCode(batch=batch, qr_slug=slug, activation_code=code),
        )

    ActivationCode.objects.bulk_create(rows, batch_size=500)
    logger.info(
        "activation.batch_generated id=%s size=%d kind=%s claim_mode=%s by=%s",
        batch.pk, size, kind, claim_mode, getattr(created_by, "pk", None),
    )
    return batch


# ---------------------------------------------------------------------------
# Claim — code mode
# ---------------------------------------------------------------------------
@transaction.atomic
def claim_code(
    *,
    user,
    qr_slug: str,
    activation_code: str,
    linked_object: Optional[models.Model] = None,
) -> ActivationCode:
    """Redeem a CODE-mode tag → mark the code consumed by ``user``.

    Optional ``linked_object`` argument — if the caller wants to attach
    the freshly-claimed code to a domain object (Item, Sticker, AssetTag),
    pass the saved instance and we'll populate the GenericForeignKey.

    Idempotency: if the code is already consumed BY THE SAME USER we
    return the existing row instead of raising — lets the frontend retry
    safely. Any other "already consumed" state raises.

    Raises:
        InvalidActivationError: no row matches (slug, code)
        WrongClaimModeError:    slug belongs to a PHOTO batch
        AlreadyConsumedError:   code consumed by someone else
    """
    qr_slug = (qr_slug or "").strip().lower()
    activation_code = (activation_code or "").strip()
    if not qr_slug or not activation_code:
        raise InvalidActivationError("qr_slug and activation_code are required.")

    try:
        code = (
            ActivationCode.objects
            .select_for_update()
            .select_related("batch")
            .get(qr_slug=qr_slug, activation_code=activation_code)
        )
    except ActivationCode.DoesNotExist as exc:
        raise InvalidActivationError(
            "Invalid activation code for this QR.",
        ) from exc

    if code.batch.claim_mode != ClaimMode.CODE:
        raise WrongClaimModeError(
            "This tag uses photo-claim — call photo_claim() instead.",
        )

    if code.consumed_at is not None:
        if code.consumed_by_id == getattr(user, "pk", None):
            return code  # idempotent retry by same user
        raise AlreadyConsumedError(
            "This code has already been claimed by someone else.",
        )

    code.consumed_at = timezone.now()
    code.consumed_by = user
    code.claim_status = ClaimStatus.CONFIRMED
    if linked_object is not None:
        code.linked_object_type = ContentType.objects.get_for_model(
            linked_object.__class__,
        )
        code.linked_object_id = linked_object.pk
    code.save(
        update_fields=[
            "consumed_at", "consumed_by", "claim_status",
            "linked_object_type", "linked_object_id",
        ],
    )
    logger.info(
        "activation.code_claimed code_id=%s by=%s linked=%s",
        code.pk, getattr(user, "pk", None),
        f"{code.linked_object_type_id}:{code.linked_object_id}"
        if code.linked_object_id else None,
    )
    return code


# ---------------------------------------------------------------------------
# Claim — photo mode (first-claim wins provisionally; window for disputes)
# ---------------------------------------------------------------------------
@transaction.atomic
def photo_claim(
    *,
    user,
    qr_slug: str,
    photo,
    message: str = "",
    linked_object: Optional[models.Model] = None,
) -> tuple[ActivationCode, bool]:
    """Redeem (or dispute) a PHOTO-mode tag.

    Returns ``(code, was_first_claim)``.

    - First scanner: marks the :class:`ActivationCode` consumed, stores
      the proof photo, sets ``claim_status=PROVISIONAL`` and
      ``provisional_until=now + ACTIVATION_PROVISIONAL_HOURS``. Optionally
      attaches a caller-provided domain object.
    - Subsequent scanner during the provisional window: creates an
      :class:`OwnershipDispute` row pointing at the existing code. Does
      NOT reassign ownership — that's a manual admin decision after review.
    - After the window closes (claim_status != PROVISIONAL): raises
      :class:`AlreadyConsumedError`. Disputes-after-window are a job for
      a separate moderation/report flow, not this service.

    Raises:
        InvalidActivationError: slug not in any batch
        WrongClaimModeError:    slug belongs to a CODE-mode batch
        AlreadyConsumedError:   provisional window already closed
        AlreadyDisputedError:   same user filing twice
    """
    qr_slug = (qr_slug or "").strip().lower()
    if not qr_slug:
        raise InvalidActivationError("qr_slug is required.")

    code = (
        ActivationCode.objects
        .select_for_update()
        .select_related("batch")
        .filter(qr_slug=qr_slug)
        .first()
    )
    if code is None:
        raise InvalidActivationError("This QR is not in any batch.")
    if code.batch.claim_mode != ClaimMode.PHOTO:
        raise WrongClaimModeError(
            "This QR uses a code — call claim_code() instead.",
        )

    # ---- First claim ever on this slug ------------------------------------
    if code.consumed_at is None:
        now = timezone.now()
        code.consumed_at = now
        code.consumed_by = user
        code.proof_photo = photo
        code.claim_status = ClaimStatus.PROVISIONAL
        code.provisional_until = now + timedelta(hours=_provisional_hours())
        if linked_object is not None:
            code.linked_object_type = ContentType.objects.get_for_model(
                linked_object.__class__,
            )
            code.linked_object_id = linked_object.pk
        code.save(
            update_fields=[
                "consumed_at", "consumed_by", "proof_photo",
                "claim_status", "provisional_until",
                "linked_object_type", "linked_object_id",
            ],
        )
        logger.info(
            "activation.photo_claim_first code_id=%s by=%s",
            code.pk, getattr(user, "pk", None),
        )
        return code, True

    # ---- Subsequent claim during the window — file a dispute --------------
    if code.claim_status != ClaimStatus.PROVISIONAL:
        raise AlreadyConsumedError(
            "The dispute window has closed for this tag. "
            "File a moderation report instead.",
        )
    if code.consumed_by_id == getattr(user, "pk", None):
        # Same user re-uploading — silently accept (idempotent).
        return code, False
    if OwnershipDispute.objects.filter(code=code, claimer=user).exists():
        raise AlreadyDisputedError(
            "You have already disputed ownership of this tag.",
        )

    OwnershipDispute.objects.create(
        code=code,
        claimer=user,
        proof_photo=photo,
        claimer_message=(message or "")[:2000],
    )
    logger.info(
        "activation.dispute_filed code_id=%s claimer=%s",
        code.pk, getattr(user, "pk", None),
    )
    return code, False


# ---------------------------------------------------------------------------
# Dispute handling
# ---------------------------------------------------------------------------
@transaction.atomic
def mark_disputed(code: ActivationCode) -> ActivationCode:
    """Force-flag a code as DISPUTED (admin / manual escalation hook)."""
    code.claim_status = ClaimStatus.DISPUTED
    code.save(update_fields=["claim_status"])
    return code


def confirm_provisional() -> tuple[int, int]:
    """Close the provisional window for codes whose time is up.

    Returns ``(confirmed_count, disputed_count)``. No outstanding dispute
    → :data:`ClaimStatus.CONFIRMED`. Any unresolved dispute →
    :data:`ClaimStatus.DISPUTED` (admin review).

    Called hourly by :func:`tasks.confirm_provisional_claims`.
    """
    now = timezone.now()
    qs = ActivationCode.objects.filter(
        claim_status=ClaimStatus.PROVISIONAL,
        provisional_until__lt=now,
    )
    confirmed = 0
    disputed = 0
    for code in qs:
        has_dispute = OwnershipDispute.objects.filter(
            code=code, resolved_at__isnull=True,
        ).exists()
        if has_dispute:
            code.claim_status = ClaimStatus.DISPUTED
            disputed += 1
        else:
            code.claim_status = ClaimStatus.CONFIRMED
            code.provisional_until = None
            confirmed += 1
        code.save(update_fields=["claim_status", "provisional_until"])
    if confirmed or disputed:
        logger.info(
            "activation.confirm_provisional confirmed=%d disputed=%d",
            confirmed, disputed,
        )
    return confirmed, disputed


# ---------------------------------------------------------------------------
# CSV export — partner deliverable
# ---------------------------------------------------------------------------
def bulk_export_csv(
    batch_id: int,
    *,
    frontend_base: str = "",
) -> bytes:
    """Export a batch's codes as a partner-ready CSV.

    Columns: ``qr_slug, activation_code, public_url, activation_url``.

    - ``public_url`` is the URL the printed QR encodes (``/q/<slug>/``).
    - ``activation_url`` is the deep-link the customer can also type
      manually (``/activate?slug=...&code=...``).

    Empty for the ``activation_code``/``activation_url`` columns on
    PHOTO-mode batches.

    Returns UTF-8 bytes (suitable for ``HttpResponse``).
    """
    base = (frontend_base or getattr(settings, "FRONTEND_URL", "") or "").rstrip("/")

    codes = (
        ActivationCode.objects
        .filter(batch_id=batch_id)
        .order_by("qr_slug")
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["qr_slug", "activation_code", "public_url", "activation_url"])
    for c in codes:
        public_url = f"{base}/q/{c.qr_slug}" if base else f"/q/{c.qr_slug}"
        if c.activation_code:
            activation_url = (
                f"{base}/activate?slug={c.qr_slug}&code={c.activation_code}"
                if base
                else f"/activate?slug={c.qr_slug}&code={c.activation_code}"
            )
        else:
            activation_url = ""
        writer.writerow([c.qr_slug, c.activation_code, public_url, activation_url])
    return buf.getvalue().encode("utf-8")
