"""Batch-generation tests."""
from __future__ import annotations

import pytest

from qr_tag_activation_batches.models import (
    ActivationCode,
    ClaimMode,
    ClaimStatus,
)
from qr_tag_activation_batches.services import (
    BatchSizeError,
    generate_batch,
)


@pytest.mark.django_db
def test_generate_batch_creates_n_codes(admin_user):
    batch = generate_batch(
        size=10,
        kind="b2c_retail",
        tag_format="sticker",
        created_by=admin_user,
    )
    assert batch.size == 10
    assert batch.codes.count() == 10
    # All have unique slugs + codes (CODE mode default)
    slugs = list(batch.codes.values_list("qr_slug", flat=True))
    codes = list(batch.codes.values_list("activation_code", flat=True))
    assert len(set(slugs)) == 10
    assert len(set(codes)) == 10
    assert all(len(c) == 6 and c.isdigit() for c in codes)


@pytest.mark.django_db
def test_generate_batch_photo_mode_has_no_codes(admin_user):
    batch = generate_batch(
        size=5,
        kind="internal",
        tag_format="patch",
        claim_mode=ClaimMode.PHOTO,
        created_by=admin_user,
    )
    assert batch.size == 5
    assert batch.codes.count() == 5
    assert all(c.activation_code == "" for c in batch.codes.all())


@pytest.mark.django_db
def test_generate_batch_rejects_invalid_size(admin_user):
    with pytest.raises(BatchSizeError):
        generate_batch(size=0, kind="b2c_retail", tag_format="sticker")
    with pytest.raises(BatchSizeError):
        generate_batch(size=10_000_001, kind="b2c_retail", tag_format="sticker")


@pytest.mark.django_db
def test_generated_codes_default_to_confirmed_status(code_batch):
    statuses = set(code_batch.codes.values_list("claim_status", flat=True))
    assert statuses == {ClaimStatus.CONFIRMED}


@pytest.mark.django_db
def test_slugs_are_globally_unique_across_batches(admin_user):
    b1 = generate_batch(size=20, kind="b2c_retail", tag_format="sticker")
    b2 = generate_batch(size=20, kind="b2c_retail", tag_format="sticker")
    all_slugs = list(
        ActivationCode.objects
        .filter(batch_id__in=[b1.pk, b2.pk])
        .values_list("qr_slug", flat=True)
    )
    assert len(set(all_slugs)) == 40
