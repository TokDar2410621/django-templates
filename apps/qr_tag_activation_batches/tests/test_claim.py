"""Claim flow tests — CODE mode + PHOTO mode."""
from __future__ import annotations

import pytest

from qr_tag_activation_batches.models import ClaimStatus, OwnershipDispute
from qr_tag_activation_batches.services import (
    AlreadyConsumedError,
    AlreadyDisputedError,
    InvalidActivationError,
    WrongClaimModeError,
    claim_code,
    confirm_provisional,
    photo_claim,
)


# ---------------------------------------------------------------------------
# CODE mode
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_claim_code_marks_consumed(user, code_batch):
    code = code_batch.codes.first()
    claimed = claim_code(
        user=user,
        qr_slug=code.qr_slug,
        activation_code=code.activation_code,
    )
    assert claimed.consumed_at is not None
    assert claimed.consumed_by_id == user.pk
    assert claimed.claim_status == ClaimStatus.CONFIRMED


@pytest.mark.django_db
def test_claim_code_wrong_code_rejected(user, code_batch):
    code = code_batch.codes.first()
    with pytest.raises(InvalidActivationError):
        claim_code(
            user=user,
            qr_slug=code.qr_slug,
            activation_code="000000",
        )


@pytest.mark.django_db
def test_claim_code_already_consumed_by_other_user(user, other_user, code_batch):
    code = code_batch.codes.first()
    claim_code(
        user=user,
        qr_slug=code.qr_slug,
        activation_code=code.activation_code,
    )
    with pytest.raises(AlreadyConsumedError):
        claim_code(
            user=other_user,
            qr_slug=code.qr_slug,
            activation_code=code.activation_code,
        )


@pytest.mark.django_db
def test_claim_code_idempotent_same_user(user, code_batch):
    code = code_batch.codes.first()
    first = claim_code(
        user=user,
        qr_slug=code.qr_slug,
        activation_code=code.activation_code,
    )
    second = claim_code(
        user=user,
        qr_slug=code.qr_slug,
        activation_code=code.activation_code,
    )
    assert first.pk == second.pk
    assert second.consumed_at == first.consumed_at


@pytest.mark.django_db
def test_claim_code_rejects_photo_batch(user, photo_batch):
    code = photo_batch.codes.first()
    with pytest.raises(WrongClaimModeError):
        claim_code(
            user=user,
            qr_slug=code.qr_slug,
            activation_code="123456",
        )


# ---------------------------------------------------------------------------
# PHOTO mode
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_photo_claim_first_wins_provisionally(user, photo_batch, fake_photo):
    code = photo_batch.codes.first()
    claimed, was_first = photo_claim(
        user=user,
        qr_slug=code.qr_slug,
        photo=fake_photo,
        message="It's mine.",
    )
    assert was_first is True
    assert claimed.consumed_by_id == user.pk
    assert claimed.claim_status == ClaimStatus.PROVISIONAL
    assert claimed.provisional_until is not None


@pytest.mark.django_db
def test_photo_claim_second_files_dispute(
    user, other_user, photo_batch, fake_photo,
):
    code = photo_batch.codes.first()
    photo_claim(user=user, qr_slug=code.qr_slug, photo=fake_photo)
    fake_photo.seek(0)
    _, was_first = photo_claim(
        user=other_user, qr_slug=code.qr_slug, photo=fake_photo,
    )
    assert was_first is False
    assert OwnershipDispute.objects.filter(code=code, claimer=other_user).count() == 1


@pytest.mark.django_db
def test_photo_claim_same_user_idempotent(user, photo_batch, fake_photo):
    code = photo_batch.codes.first()
    photo_claim(user=user, qr_slug=code.qr_slug, photo=fake_photo)
    fake_photo.seek(0)
    _, was_first_again = photo_claim(
        user=user, qr_slug=code.qr_slug, photo=fake_photo,
    )
    assert was_first_again is False
    assert OwnershipDispute.objects.filter(code=code).count() == 0


@pytest.mark.django_db
def test_photo_claim_duplicate_dispute_rejected(
    user, other_user, photo_batch, fake_photo,
):
    code = photo_batch.codes.first()
    photo_claim(user=user, qr_slug=code.qr_slug, photo=fake_photo)
    fake_photo.seek(0)
    photo_claim(user=other_user, qr_slug=code.qr_slug, photo=fake_photo)
    fake_photo.seek(0)
    with pytest.raises(AlreadyDisputedError):
        photo_claim(user=other_user, qr_slug=code.qr_slug, photo=fake_photo)


@pytest.mark.django_db
def test_photo_claim_rejects_code_batch(user, code_batch, fake_photo):
    code = code_batch.codes.first()
    with pytest.raises(WrongClaimModeError):
        photo_claim(user=user, qr_slug=code.qr_slug, photo=fake_photo)


@pytest.mark.django_db
def test_photo_claim_unknown_slug(user, fake_photo):
    with pytest.raises(InvalidActivationError):
        photo_claim(user=user, qr_slug="nonexistent", photo=fake_photo)


# ---------------------------------------------------------------------------
# confirm_provisional — Celery-friendly closer
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_confirm_provisional_promotes_no_dispute_to_confirmed(
    user, photo_batch, fake_photo,
):
    from datetime import timedelta

    from django.utils import timezone

    code = photo_batch.codes.first()
    photo_claim(user=user, qr_slug=code.qr_slug, photo=fake_photo)
    # Force the window to be over.
    code.refresh_from_db()
    code.provisional_until = timezone.now() - timedelta(seconds=1)
    code.save(update_fields=["provisional_until"])

    confirmed, disputed = confirm_provisional()
    assert confirmed == 1
    assert disputed == 0
    code.refresh_from_db()
    assert code.claim_status == ClaimStatus.CONFIRMED
    assert code.provisional_until is None


@pytest.mark.django_db
def test_confirm_provisional_disputed_path(
    user, other_user, photo_batch, fake_photo,
):
    code = photo_batch.codes.first()
    photo_claim(user=user, qr_slug=code.qr_slug, photo=fake_photo)
    fake_photo.seek(0)
    photo_claim(user=other_user, qr_slug=code.qr_slug, photo=fake_photo)

    from datetime import timedelta

    from django.utils import timezone

    code.refresh_from_db()
    code.provisional_until = timezone.now() - timedelta(seconds=1)
    code.save(update_fields=["provisional_until"])

    confirmed, disputed = confirm_provisional()
    assert confirmed == 0
    assert disputed == 1
    code.refresh_from_db()
    assert code.claim_status == ClaimStatus.DISPUTED
