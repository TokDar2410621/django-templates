"""Lectures : les appareils d'un utilisateur."""
from __future__ import annotations

from django.db.models import QuerySet

from .models import PushDevice, empreinte


def devices_for_user(user) -> QuerySet[PushDevice]:
    """Tous les appareils push d'un utilisateur (navigateurs et telephones)."""
    return PushDevice.objects.filter(user=user)


def device_for_token(user, token: str) -> QuerySet[PushDevice]:
    """L'appareil de CET utilisateur qui porte ce jeton (ou cet endpoint)."""
    return PushDevice.objects.filter(user=user, token_hash=empreinte(token))


def device_summaries(user) -> list[dict]:
    """Etat de chaque appareil, pour le diagnostic : type, dernier envoi reussi, derniere erreur."""
    return list(devices_for_user(user).values("id", "kind", "last_used_at", "last_error"))
