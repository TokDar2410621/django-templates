"""Business rules: who may talk to whom, and event broadcasting.

Views stay HTTP-only; every rule lives here so a Celery task or a consumer
can reuse it identically.
"""
from __future__ import annotations

import logging

from django.contrib.auth import get_user_model

from . import store
from .models import Block

logger = logging.getLogger(__name__)


class MessagingError(Exception):
    """Business refusal, mapped to 4xx by the views."""

    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.code = code


def broadcast(conv_id: str, event: dict) -> None:
    """Push an event to the conversation group. Silently a no-op when no
    channel layer is configured (WSGI showcase, tests without channels)."""
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        layer = get_channel_layer()
        if layer is None:
            return
        async_to_sync(layer.group_send)(f"rtm_{conv_id}", {"type": "rtm_event", "event": event})
    except Exception:  # jamais bloquant : le message est deja persiste
        logger.warning("realtime_messaging: broadcast impossible", exc_info=True)


def ouvrir_conversation(*, demandeur, participant_ids, ref: str | None = None) -> tuple[str, bool]:
    ids = {str(p) for p in participant_ids} | {str(demandeur.id)}
    if len(ids) < 2:
        raise MessagingError("Il faut au moins un autre participant.")
    User = get_user_model()
    autres = User.objects.filter(pk__in=[p for p in ids if p != str(demandeur.id)])
    if autres.count() != len(ids) - 1:
        raise MessagingError("Participant inconnu.", code=404)
    for autre in autres:
        if Block.between(demandeur, autre):
            raise MessagingError("Conversation impossible avec cet utilisateur.", code=403)
    return store.create_or_get_conversation(participant_ids=ids, ref=ref)


def envoyer_message(
    *,
    expediteur,
    conv_id: str,
    content: str,
    msg_type: str = "text",
    duration: int | None = None,
    reply_to_id: str | None = None,
) -> dict:
    if not store.user_is_participant(conv_id, expediteur.id):
        raise MessagingError("Tu ne participes pas a cette conversation.", code=403)
    content = (content or "").strip()
    if not content:
        raise MessagingError("Message vide.")
    if msg_type not in ("text", "photo", "video", "audio"):
        raise MessagingError("Type de message inconnu.")
    User = get_user_model()
    for autre_id in store.other_participants(conv_id, expediteur.id):
        autre = User.objects.filter(pk=autre_id).first()
        if autre and Block.between(expediteur, autre):
            raise MessagingError("Conversation bloquee.", code=403)
    message = store.add_message(
        conv_id=conv_id,
        sender_id=expediteur.id,
        content=content,
        msg_type=msg_type,
        duration=duration,
        reply_to_id=reply_to_id,
    )
    broadcast(conv_id, {"kind": "message", "message": message})
    return message
