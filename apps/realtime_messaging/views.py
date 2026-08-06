"""REST surface. HTTP only: rules live in services.py, storage in store.py.

Dormant pattern: without a configured Redis the endpoints answer 503 with an
explicit message (same language as the library showcase) instead of 500.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import store
from .models import Block
from .services import MessagingError, broadcast, envoyer_message, ouvrir_conversation


def _dormant() -> Response:
    return Response(
        {"detail": "realtime_messaging est dormant : configure REALTIME_MESSAGING_REDIS_URL (ou REDIS_URL)."},
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


class ConversationsView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        if not store.redis_url():
            return _dormant()
        return Response(store.list_user_conversations(request.user.id))

    def post(self, request):
        if not store.redis_url():
            return _dormant()
        try:
            conv_id, created = ouvrir_conversation(
                demandeur=request.user,
                participant_ids=request.data.get("participant_ids") or [],
                ref=(request.data.get("ref") or None),
            )
        except MessagingError as e:
            return Response({"detail": str(e)}, status=e.code)
        return Response(
            {"id": conv_id, "created": created},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class MessagesView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, conv_id):
        if not store.redis_url():
            return _dormant()
        if not store.user_is_participant(conv_id, request.user.id):
            return Response(status=status.HTTP_403_FORBIDDEN)
        return Response(store.list_messages(conv_id))

    def post(self, request, conv_id):
        if not store.redis_url():
            return _dormant()
        try:
            duration = request.data.get("duration")
            message = envoyer_message(
                expediteur=request.user,
                conv_id=conv_id,
                content=request.data.get("content", ""),
                msg_type=request.data.get("msg_type", "text"),
                duration=int(duration) if duration is not None else None,
                reply_to_id=request.data.get("reply_to_id"),
            )
        except MessagingError as e:
            return Response({"detail": str(e)}, status=e.code)
        except (TypeError, ValueError):
            return Response({"detail": "duration invalide."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(message, status=status.HTTP_201_CREATED)


class MarkReadView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, conv_id):
        if not store.redis_url():
            return _dormant()
        if not store.user_is_participant(conv_id, request.user.id):
            return Response(status=status.HTTP_403_FORBIDDEN)
        n = store.mark_conversation_read(conv_id, request.user.id)
        if n:
            broadcast(conv_id, {"kind": "read", "reader_id": str(request.user.id), "count": n})
        return Response({"marked": n})


class MessageView(APIView):
    permission_classes = (IsAuthenticated,)

    def delete(self, request, msg_id):
        if not store.redis_url():
            return _dormant()
        conv_id = store.delete_message(msg_id, request.user.id)
        if conv_id is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        broadcast(conv_id, {"kind": "deleted", "message_id": msg_id})
        return Response(status=status.HTTP_204_NO_CONTENT)


class ReactionView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, msg_id):
        if not store.redis_url():
            return _dormant()
        message = store.get_message(msg_id)
        if not message or not store.user_is_participant(message["conversation_id"], request.user.id):
            return Response(status=status.HTTP_404_NOT_FOUND)
        emoji = (request.data.get("emoji") or "").strip()
        if not emoji or len(emoji) > 8:
            return Response({"detail": "emoji invalide."}, status=status.HTTP_400_BAD_REQUEST)
        reactions = store.toggle_reaction(msg_id, request.user.id, emoji)
        broadcast(message["conversation_id"], {"kind": "reaction", "message_id": msg_id, "reactions": reactions})
        return Response({"reactions": reactions})


class BlocksView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        cible = request.data.get("user_id")
        if not cible or str(cible) == str(request.user.id):
            return Response({"detail": "user_id invalide."}, status=status.HTTP_400_BAD_REQUEST)
        Block.objects.get_or_create(
            blocker=request.user,
            blocked_id=cible,
            defaults={"reason": (request.data.get("reason") or "")[:120]},
        )
        return Response(status=status.HTTP_201_CREATED)

    def delete(self, request):
        cible = request.data.get("user_id")
        Block.objects.filter(blocker=request.user, blocked_id=cible).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
