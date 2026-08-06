"""DRF serializers for the public push API."""
from __future__ import annotations

from rest_framework import serializers

from .models import PushSubscription


class PushSubscriptionSerializer(serializers.ModelSerializer):
    """Round-trip serializer for the ``PushSubscription`` model."""

    class Meta:
        model = PushSubscription
        fields = (
            "id",
            "endpoint",
            "p256dh",
            "auth",
            "user_agent",
            "created_at",
            "last_used_at",
        )
        read_only_fields = ("id", "created_at", "last_used_at")


class PushSubscribeRequestSerializer(serializers.Serializer):
    """Validates incoming subscribe payloads.

    Matches the shape returned by ``PushSubscription.toJSON()`` in the
    browser: ``{endpoint, keys: {p256dh, auth}}``.
    """

    endpoint = serializers.URLField(max_length=500)
    keys = serializers.DictField(child=serializers.CharField(max_length=255))

    def validate_keys(self, value: dict) -> dict:
        missing = [k for k in ("p256dh", "auth") if not (value.get(k) or "").strip()]
        if missing:
            raise serializers.ValidationError(
                f"keys.{', keys.'.join(missing)} required",
            )
        return value
