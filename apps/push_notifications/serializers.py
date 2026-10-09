from __future__ import annotations

import re

from rest_framework import serializers

from .models import PushDevice

EXPO_TOKEN = re.compile(r"^Expo(nent)?PushToken\[[^\]]+\]$")
APNS_TOKEN = re.compile(r"^[0-9a-fA-F]{64,200}$")


class WebKeysSerializer(serializers.Serializer):
    p256dh = serializers.CharField(max_length=255)
    auth = serializers.CharField(max_length=255)


class WebSubscriptionSerializer(serializers.Serializer):
    """Exactement ce que rend subscription.toJSON() dans le navigateur."""

    endpoint = serializers.URLField(max_length=2000)
    keys = WebKeysSerializer()

    def validate_endpoint(self, value: str) -> str:
        if not value.startswith("https://"):
            raise serializers.ValidationError("L'endpoint d'un abonnement Web Push est toujours en https.")
        return value


class DeviceSerializer(serializers.Serializer):
    """Corps de POST /appareils/.

    Navigateur : {"kind": "web", "subscription": <subscription.toJSON()>}
    Mobile     : {"kind": "fcm" | "apns" | "expo", "token": "...", "sandbox": false}
    """

    kind = serializers.ChoiceField(choices=[k for k, _ in PushDevice.KINDS])
    subscription = WebSubscriptionSerializer(required=False)
    token = serializers.CharField(required=False, max_length=4096)
    sandbox = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs: dict) -> dict:
        kind = attrs["kind"]
        if kind == PushDevice.WEB:
            if "subscription" not in attrs:
                raise serializers.ValidationError({"subscription": "Requis pour un navigateur."})
            return attrs
        token = (attrs.get("token") or "").strip()
        if not token:
            raise serializers.ValidationError({"token": "Requis pour un appareil mobile."})
        if kind == PushDevice.EXPO and not EXPO_TOKEN.match(token):
            raise serializers.ValidationError({"token": "Un jeton Expo ressemble a ExponentPushToken[...]."})
        if kind == PushDevice.APNS and not APNS_TOKEN.match(token):
            raise serializers.ValidationError({"token": "Un jeton APNs est une suite hexadecimale (64 caracteres ou plus)."})
        attrs["token"] = token
        return attrs


class UnregisterSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=4096, help_text="Le jeton mobile, ou l'endpoint du navigateur.")
