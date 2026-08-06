"""Models for multichannel notifications.

PushSubscription stores Web Push (VAPID) endpoints — one row per
browser/device that the user has opted in. A single user may legitimately
have several rows (laptop Chrome, phone Safari, tablet Firefox, etc.).

NotificationLog is intentionally OPTIONAL. It records every send attempt
(channel, status, error) so operators can answer "did the user get the
email?" from the admin. Disable it via
``NOTIFICATIONS_LOG_DELIVERIES = False`` if you'd rather not store this
trace (compliance / storage cost).
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


# ---------------------------------------------------------------------------
# Push subscription — Web Push (VAPID)
# ---------------------------------------------------------------------------
class PushSubscription(models.Model):
    """One Web Push (VAPID) subscription per browser/device.

    The ``endpoint`` is globally unique (Mozilla / Google / Apple push
    services hand out unique URLs per subscription); we ``update_or_create``
    on it so a user re-subscribing from the same device updates rather than
    duplicates.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="push_subscriptions",
    )
    endpoint = models.URLField(max_length=500, unique=True)
    # Browser-generated key pair used to encrypt push payloads (RFC 8291).
    p256dh = models.CharField(max_length=255)
    auth = models.CharField(max_length=255)
    user_agent = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notifications_push_subscription"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["user", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"Push sub user={self.user_id} ({self.user_agent[:30]})"


# ---------------------------------------------------------------------------
# Optional delivery log
# ---------------------------------------------------------------------------
class NotificationLog(models.Model):
    """Persistent record of every send attempt (success or failure).

    Useful for support ("did the user receive the password-reset email?")
    and for product analytics (open rates require provider webhooks — out
    of scope here, but the row exists to be joined).
    """

    CHANNEL_EMAIL = "email"
    CHANNEL_PUSH = "push"
    CHANNEL_SMS = "sms"
    CHANNEL_CHOICES = (
        (CHANNEL_EMAIL, "Email"),
        (CHANNEL_PUSH, "Web Push"),
        (CHANNEL_SMS, "SMS"),
    )

    STATUS_SENT = "sent"
    STATUS_SKIPPED = "skipped"      # degraded mode, no key, opted out, etc.
    STATUS_FAILED = "failed"        # provider error, network, bad config
    STATUS_CHOICES = (
        (STATUS_SENT, "Sent"),
        (STATUS_SKIPPED, "Skipped"),
        (STATUS_FAILED, "Failed"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_logs",
        null=True,
        blank=True,
    )
    channel = models.CharField(max_length=16, choices=CHANNEL_CHOICES, db_index=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, db_index=True)

    # Per-channel best-effort identifying info; not normalized because the
    # three channels carry different metadata and we want a single ad-hoc
    # query surface in the admin.
    subject = models.CharField(max_length=255, blank=True, default="")
    target = models.CharField(
        max_length=320,
        blank=True,
        default="",
        help_text="Destination — email address, phone E.164, or push endpoint.",
    )
    provider_message_id = models.CharField(max_length=255, blank=True, default="")
    error = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "notifications_log"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["channel", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"[{self.channel}] {self.status} {self.subject[:40]}"
