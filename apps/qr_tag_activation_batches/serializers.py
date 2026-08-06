"""DRF serializers for the activation API.

Shapes:

    - :class:`ActivationBatchSerializer`   admin / staff read of a batch
    - :class:`ActivationCodeSerializer`    admin / staff read of a code row
    - :class:`ClaimRequestSerializer`      input for POST /api/activation/claim/
    - :class:`PhotoClaimRequestSerializer` input for POST /api/activation/photo-claim/
    - :class:`ScanResponseSerializer`      output for GET /q/<slug>/
"""
from __future__ import annotations

from rest_framework import serializers

from .models import ActivationBatch, ActivationCode, ClaimMode, ClaimStatus


# ---------------------------------------------------------------------------
# Read shapes
# ---------------------------------------------------------------------------
class ActivationBatchSerializer(serializers.ModelSerializer):
    consumed_count = serializers.IntegerField(read_only=True)
    remaining_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = ActivationBatch
        fields = (
            "id",
            "kind",
            "tag_format",
            "claim_mode",
            "size",
            "partner_label",
            "notes",
            "consumed_count",
            "remaining_count",
            "created_at",
        )
        read_only_fields = fields


class ActivationCodeSerializer(serializers.ModelSerializer):
    """Admin/staff read. Hides nothing because this is staff-only output."""

    class Meta:
        model = ActivationCode
        fields = (
            "id",
            "batch",
            "qr_slug",
            "activation_code",
            "consumed_at",
            "consumed_by",
            "claim_status",
            "provisional_until",
            "linked_object_type",
            "linked_object_id",
        )
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Write shapes
# ---------------------------------------------------------------------------
class ClaimRequestSerializer(serializers.Serializer):
    """Input for ``POST /api/activation/claim/`` (CODE mode)."""

    qr_slug = serializers.CharField(max_length=16)
    activation_code = serializers.CharField(max_length=16)

    def validate_qr_slug(self, value: str) -> str:
        return value.strip().lower()

    def validate_activation_code(self, value: str) -> str:
        return value.strip()


class PhotoClaimRequestSerializer(serializers.Serializer):
    """Input for ``POST /api/activation/photo-claim/`` (PHOTO mode)."""

    qr_slug = serializers.CharField(max_length=16)
    photo = serializers.ImageField()
    message = serializers.CharField(
        max_length=2000, required=False, allow_blank=True, default="",
    )

    def validate_qr_slug(self, value: str) -> str:
        return value.strip().lower()


# ---------------------------------------------------------------------------
# Scan response — what GET /q/<slug>/ returns (JSON shape)
# ---------------------------------------------------------------------------
class ScanResponseSerializer(serializers.Serializer):
    """Output for ``GET /q/<slug>/`` — activation state for the frontend.

    A caller that wants HTML instead of JSON should override the view
    (see ``views.ScanView`` docstring) and reuse this serializer's logic
    via :func:`ScanResponseSerializer.from_code`.
    """

    qr_slug = serializers.CharField()
    found = serializers.BooleanField()
    claimable = serializers.BooleanField()
    claim_mode = serializers.ChoiceField(
        choices=ClaimMode.choices, allow_null=True,
    )
    claim_status = serializers.ChoiceField(
        choices=ClaimStatus.choices, allow_null=True,
    )
    consumed = serializers.BooleanField()

    @classmethod
    def from_code(cls, slug: str, code) -> dict:
        """Build the response payload from a slug + (optional) code row."""
        if code is None:
            return {
                "qr_slug": slug,
                "found": False,
                "claimable": False,
                "claim_mode": None,
                "claim_status": None,
                "consumed": False,
            }

        consumed = code.consumed_at is not None
        # PHOTO tags stay "claimable" forever — late scanners can file a
        # dispute during the provisional window. CODE tags are claimable
        # exactly once.
        if code.batch.claim_mode == ClaimMode.PHOTO:
            claimable = (
                not consumed or code.claim_status == ClaimStatus.PROVISIONAL
            )
        else:
            claimable = not consumed

        return {
            "qr_slug": slug,
            "found": True,
            "claimable": claimable,
            "claim_mode": code.batch.claim_mode,
            "claim_status": code.claim_status,
            "consumed": consumed,
        }
