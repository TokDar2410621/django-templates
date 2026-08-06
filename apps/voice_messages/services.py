"""Validation and storage of voice notes. All limits are settings with sane
defaults (getattr): a project tightens them without touching the app."""
from __future__ import annotations

import logging

from django.conf import settings

from .models import VoiceMessage

logger = logging.getLogger(__name__)

# Formats produits par MediaRecorder (web), iOS (m4a/mp4) et Android.
TYPES_DEFAUT = (
    "audio/webm",
    "audio/ogg",
    "audio/mpeg",
    "audio/mp4",
    "audio/x-m4a",
    "audio/aac",
    "audio/wav",
)


class VoiceError(Exception):
    """Business refusal, mapped to 4xx by the views."""

    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.code = code


def types_permis() -> tuple[str, ...]:
    return tuple(getattr(settings, "VOICE_MESSAGES_ALLOWED_TYPES", TYPES_DEFAUT))


def taille_max() -> int:
    return int(getattr(settings, "VOICE_MESSAGES_MAX_BYTES", 10 * 1024 * 1024))


def duree_max() -> int:
    return int(getattr(settings, "VOICE_MESSAGES_MAX_SECONDS", 300))


def enregistrer(*, sender, fichier, duration_seconds, ref: str = "") -> VoiceMessage:
    """Validate then persist a voice note. Raises VoiceError on refusal.

    ``duration_seconds`` comes from the client (MediaRecorder knows it); it is
    BOUNDED here, never trusted blindly. Server-side probing (ffprobe) is a
    per-project upgrade documented in SETTINGS.md.
    """
    if fichier is None:
        raise VoiceError("Aucun fichier fourni.")
    ctype = (getattr(fichier, "content_type", "") or "").lower().split(";")[0].strip()
    if ctype not in types_permis():
        raise VoiceError(f"Type audio refuse ({ctype or 'inconnu'}).", code=415)
    if fichier.size > taille_max():
        raise VoiceError("Fichier trop lourd.", code=413)
    try:
        duree = int(duration_seconds)
    except (TypeError, ValueError):
        raise VoiceError("duration_seconds invalide.")
    if not 0 < duree <= duree_max():
        raise VoiceError(f"Duree hors bornes (1 a {duree_max()} s).")

    note = VoiceMessage.objects.create(
        sender=sender,
        file=fichier,
        mime_type=ctype,
        size_bytes=fichier.size,
        duration_seconds=duree,
        ref=(ref or "")[:120],
    )
    logger.info("voice_messages: note %s enregistree (%ss, %so)", note.uuid, duree, fichier.size)
    return note
