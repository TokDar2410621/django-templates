"""Read-only WebSocket firehose per conversation.

Canonical Channels pattern (proven in FIN and SMN): writes go through the
DRF views (validation, blocks, rate-limit concentrated there), which
broadcast on the group ``rtm_<conv_id>``; this consumer relays events to
the client and seeds it with history at connect.
"""
from __future__ import annotations

import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from . import store


class ConversationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.close(code=4401)
            return
        self.conv_id = self.scope["url_route"]["kwargs"]["conv_id"]
        self.group = f"rtm_{self.conv_id}"

        est_participant = await database_sync_to_async(store.user_is_participant)(
            self.conv_id, user.id
        )
        if not est_participant:
            await self.close(code=4403)
            return

        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        messages = await database_sync_to_async(store.list_messages)(self.conv_id)
        await self.send(text_data=json.dumps({"kind": "history", "messages": messages}))

    async def disconnect(self, code):
        group = getattr(self, "group", None)
        if group:
            await self.channel_layer.group_discard(group, self.channel_name)

    async def rtm_event(self, event):
        """Relay a broadcast from services.broadcast to the client."""
        await self.send(text_data=json.dumps(event["event"]))
