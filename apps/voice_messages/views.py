"""HTTP surface: upload a note, read its metadata. HTTP only."""
from __future__ import annotations

from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import VoiceMessage
from .services import VoiceError, enregistrer


def _serialise(note: VoiceMessage) -> dict:
    return {
        "id": str(note.uuid),
        "url": note.file.url,
        "mime_type": note.mime_type,
        "size_bytes": note.size_bytes,
        "duration_seconds": note.duration_seconds,
        "ref": note.ref,
        "created_at": note.created_at.isoformat(),
    }


class UploadView(APIView):
    """POST /upload/ (multipart: file, duration_seconds, ref?) -> {id, url, ...}

    Ensuite : envoie un message dans TON systeme de chat avec
    msg_type="audio", content=<url>, duration=<duration_seconds>.
    """

    permission_classes = (IsAuthenticated,)
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request):
        try:
            note = enregistrer(
                sender=request.user,
                fichier=request.FILES.get("file"),
                duration_seconds=request.data.get("duration_seconds"),
                ref=request.data.get("ref", ""),
            )
        except VoiceError as e:
            return Response({"detail": str(e)}, status=e.code)
        return Response(_serialise(note), status=status.HTTP_201_CREATED)


class DetailView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, note_uuid):
        note = VoiceMessage.objects.filter(uuid=note_uuid).first()
        if note is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(_serialise(note))

    def delete(self, request, note_uuid):
        note = VoiceMessage.objects.filter(uuid=note_uuid, sender=request.user).first()
        if note is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        note.file.delete(save=False)
        note.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
