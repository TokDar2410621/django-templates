"""Voice notes as a standalone app.

Extracted from SMN, where audio was woven into the chat (msg_type="audio",
content=S3 URL, duration on the message). Separated on purpose: the storage
and validation of a voice note is one concern; which message carries it is
another. Integration is DECLARED, never imported: after upload, send a
message in your messaging system (e.g. realtime_messaging) with
msg_type="audio", content=<url returned here>, duration=<duration>.
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


def chemin_upload(instance: "VoiceMessage", filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "webm"
    return f"voice_messages/{instance.created_at_path}/{instance.uuid}.{ext}"


class VoiceMessage(models.Model):
    """One recorded voice note: the file, its duration, its sender."""

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="voice_messages",
    )
    file = models.FileField(upload_to=chemin_upload)
    mime_type = models.CharField(max_length=60)
    size_bytes = models.PositiveIntegerField()
    duration_seconds = models.PositiveIntegerField()
    # Ancre libre vers le systeme de messagerie ("rtm:<conv_id>", "ticket:9"...)
    # CharField et non FK : l'app reste autonome, l'integration est declaree.
    ref = models.CharField(max_length=120, blank=True, default="", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "voice_messages_voicemessage"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["sender", "-created_at"], name="vm_sender_recent_idx")]

    def __str__(self) -> str:
        return f"VoiceMessage {self.uuid} ({self.duration_seconds}s)"

    @property
    def created_at_path(self) -> str:
        from django.utils import timezone

        dt = self.created_at or timezone.now()
        return dt.strftime("%Y/%m")
