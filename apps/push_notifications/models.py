from __future__ import annotations

import hashlib

from django.conf import settings
from django.db import models


def empreinte(token: str) -> str:
    """Empreinte stable d'un jeton : sert a l'unicite (un jeton peut depasser 255 caracteres)."""
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


class PushDevice(models.Model):
    """Un appareil qui recoit des push : un navigateur, un telephone Android ou un iPhone."""

    WEB = "web"
    FCM = "fcm"
    APNS = "apns"
    EXPO = "expo"
    KINDS = [
        (WEB, "Navigateur (Web Push)"),
        (FCM, "Firebase (Android, et iPhone si l'appli utilise Firebase)"),
        (APNS, "Apple direct (iPhone sans Firebase)"),
        (EXPO, "Expo (appli React Native Expo)"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="push_devices"
    )
    kind = models.CharField(max_length=8, choices=KINDS)
    # Web : l'adresse "endpoint" de l'abonnement. Mobile : le jeton de l'appareil.
    token = models.TextField()
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    # Web Push seulement : les cles de chiffrement de l'abonnement.
    p256dh = models.CharField(max_length=255, blank=True, default="")
    auth = models.CharField(max_length=255, blank=True, default="")
    # Apple direct seulement : build Xcode = sandbox ; TestFlight et App Store = production.
    apns_sandbox = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["user", "kind"])]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} de {self.user_id}"

    def save(self, *args, **kwargs):
        self.token = self.token.strip()
        self.token_hash = empreinte(self.token)
        super().save(*args, **kwargs)
