"""DRF serializers — admin read API + Connect-callback payload."""
from __future__ import annotations

from rest_framework import serializers

from .models import Partner, PartnerProductShare, Payout


class PartnerSerializer(serializers.ModelSerializer):
    """Admin view — exposes the Connect onboarding state."""

    share_percent = serializers.SerializerMethodField()

    class Meta:
        model = Partner
        fields = (
            "id",
            "display_name",
            "payout_email",
            "default_share_bps",
            "share_percent",
            "flat_per_order_cents",
            "stripe_account_id",
            "stripe_account_verified",
            "active",
            "created_at",
        )
        read_only_fields = (
            "stripe_account_id",
            "stripe_account_verified",
            "created_at",
        )

    def get_share_percent(self, obj: Partner) -> str:
        # Return as a string to avoid float precision surprises in JSON.
        return f"{obj.share_percent:.2f}"


class PartnerProductShareSerializer(serializers.ModelSerializer):
    class Meta:
        model = PartnerProductShare
        fields = ("id", "partner", "external_product_id", "share_bps", "notes")


class PayoutSerializer(serializers.ModelSerializer):
    """Public read shape — partners see their own payouts via this."""

    class Meta:
        model = Payout
        fields = (
            "id",
            "external_order_id",
            "external_order_item_id",
            "gross_cents",
            "share_bps",
            "partner_amount_cents",
            "platform_fee_cents",
            "currency",
            "stripe_transfer_id",
            "status",
            "error",
            "created_at",
            "paid_at",
        )
        read_only_fields = fields  # ledger is append-only via the API


class ConnectCallbackSerializer(serializers.Serializer):
    """Incoming params for the OAuth callback view."""

    code = serializers.CharField(max_length=200, required=False, allow_blank=True)
    state = serializers.CharField(max_length=400, required=False, allow_blank=True)
    error = serializers.CharField(max_length=120, required=False, allow_blank=True)
