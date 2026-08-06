"""Durable side of the messaging system.

The messages themselves are EPHEMERAL (Redis, see store.py). Postgres only
keeps what must survive: blocks. Extracted from FIN/conversations; the
item-scoped ContactHistory stayed in FIN (project-specific, re-add per
project if needed).
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


class Block(models.Model):
    """Directional block. ``(blocker=A, blocked=B)`` means A blocked B: B can
    no longer open a conversation with A nor message an existing one."""

    blocker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="rtm_blocks_given",
    )
    blocked = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="rtm_blocks_received",
    )
    reason = models.CharField(max_length=120, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "realtime_messaging_block"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["blocker", "blocked"], name="rtm_unique_block_pair"),
        ]

    def __str__(self) -> str:
        return f"Block {self.blocker_id} -> {self.blocked_id}"

    @staticmethod
    def between(user_a, user_b) -> bool:
        """True when either side blocked the other."""
        return Block.objects.filter(
            models.Q(blocker=user_a, blocked=user_b) | models.Q(blocker=user_b, blocked=user_a)
        ).exists()
