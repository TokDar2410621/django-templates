# -*- coding: utf-8 -*-
"""Upload heureux + les refus qui protegent (type, taille, duree)."""
import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from voice_messages.models import VoiceMessage
from voice_messages.services import VoiceError, enregistrer

User = get_user_model()


def _audio(nom="note.webm", ctype="audio/webm", octets=b"x" * 2048):
    return SimpleUploadedFile(nom, octets, content_type=ctype)


@pytest.fixture()
def alice(db):
    return User.objects.create_user(username="alice", password="x")


def test_upload_heureux(alice):
    note = enregistrer(sender=alice, fichier=_audio(), duration_seconds=42, ref="rtm:conv-1")
    assert note.duration_seconds == 42
    assert note.mime_type == "audio/webm"
    assert note.ref == "rtm:conv-1"
    assert VoiceMessage.objects.count() == 1


def test_type_refuse(alice):
    with pytest.raises(VoiceError) as exc:
        enregistrer(sender=alice, fichier=_audio(ctype="application/pdf"), duration_seconds=10)
    assert exc.value.code == 415


def test_trop_lourd(alice, settings):
    settings.VOICE_MESSAGES_MAX_BYTES = 1024
    with pytest.raises(VoiceError) as exc:
        enregistrer(sender=alice, fichier=_audio(octets=b"x" * 2048), duration_seconds=10)
    assert exc.value.code == 413


def test_duree_hors_bornes(alice):
    with pytest.raises(VoiceError):
        enregistrer(sender=alice, fichier=_audio(), duration_seconds=0)
    with pytest.raises(VoiceError):
        enregistrer(sender=alice, fichier=_audio(), duration_seconds=10_000)


@pytest.mark.django_db
def test_api_bout_en_bout(alice):
    client = APIClient()
    client.force_authenticate(alice)
    r = client.post(
        "/api/voice/upload/",
        {"file": _audio(), "duration_seconds": 7, "ref": "rtm:conv-9"},
        format="multipart",
    )
    assert r.status_code == 201
    corps = r.json()
    assert corps["duration_seconds"] == 7 and corps["url"]

    r2 = client.get(f"/api/voice/{corps['id']}/")
    assert r2.status_code == 200

    # seul l'expediteur supprime
    intrus = User.objects.create_user(username="intrus", password="x")
    client.force_authenticate(intrus)
    assert client.delete(f"/api/voice/{corps['id']}/").status_code == 404
    client.force_authenticate(alice)
    assert client.delete(f"/api/voice/{corps['id']}/").status_code == 204
