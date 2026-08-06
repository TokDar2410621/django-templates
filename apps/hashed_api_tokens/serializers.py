"""Serializers for the token management API.

Two distinct shapes:

* ``ApiTokenSerializer`` — list/detail. The hash is NEVER exposed.
* ``CreateTokenResponseSerializer`` — POST response only. Includes the plain
  token field; this is the only place in the codebase that does.
"""
from __future__ import annotations

from rest_framework import serializers

from .models import ApiToken


class ApiTokenSerializer(serializers.ModelSerializer):
    """Read-only representation safe to expose anywhere."""

    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = ApiToken
        fields = (
            "id",
            "name",
            "key_prefix",
            "last_used_at",
            "revoked_at",
            "created_at",
            "is_active",
        )
        read_only_fields = fields


class CreateTokenRequestSerializer(serializers.Serializer):
    """POST body for creating a new token."""

    name = serializers.CharField(
        max_length=100,
        help_text="Friendly label, e.g. 'n8n production' or 'Zapier'.",
    )

    def validate_name(self, value: str) -> str:
        stripped = (value or "").strip()
        if not stripped:
            raise serializers.ValidationError("name is required.")
        return stripped[:100]


class CreateTokenResponseSerializer(serializers.ModelSerializer):
    """POST response. Contains the plain token — shown ONCE.

    The ``token`` field is NOT a model field; it's injected by the view from
    the value returned by ``services.create_token``. We assemble the
    response dict manually rather than reading from the instance so the
    plain token can never accidentally leak into a list serializer.
    """

    token = serializers.CharField(read_only=True)
    message = serializers.CharField(read_only=True)

    class Meta:
        model = ApiToken
        fields = (
            "id",
            "name",
            "key_prefix",
            "created_at",
            "token",
            "message",
        )
        read_only_fields = fields
