"""Shared pytest fixtures for qr_tag_activation_batches tests."""
from __future__ import annotations

import io

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from qr_tag_activation_batches.models import ClaimMode
from qr_tag_activation_batches.services import generate_batch


@pytest.fixture
def user(db):
    User = get_user_model()
    return User.objects.create_user(
        username="claimant",
        email="claimant@example.com",
        password="pwpwpwpw",
    )


@pytest.fixture
def other_user(db):
    User = get_user_model()
    return User.objects.create_user(
        username="rival",
        email="rival@example.com",
        password="pwpwpwpw",
    )


@pytest.fixture
def admin_user(db):
    User = get_user_model()
    return User.objects.create_user(
        username="ops",
        email="ops@example.com",
        password="pwpwpwpw",
    )


@pytest.fixture
def code_batch(db, admin_user):
    """A small CODE-mode batch."""
    return generate_batch(
        size=3,
        kind="b2c_retail",
        tag_format="sticker",
        claim_mode=ClaimMode.CODE,
        partner_label="test-batch",
        created_by=admin_user,
    )


@pytest.fixture
def photo_batch(db, admin_user):
    """A small PHOTO-mode batch."""
    return generate_batch(
        size=2,
        kind="b2c_retail",
        tag_format="sticker",
        claim_mode=ClaimMode.PHOTO,
        partner_label="test-photo-batch",
        created_by=admin_user,
    )


@pytest.fixture
def fake_photo():
    """A 1-byte fake JPEG, good enough for ImageField mock uploads.

    The proof_photo field stores whatever bytes you give it; tests don't
    need a real image.
    """
    return SimpleUploadedFile(
        "proof.jpg",
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01",
        content_type="image/jpeg",
    )
