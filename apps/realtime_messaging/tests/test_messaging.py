# -*- coding: utf-8 -*-
"""Happy path + les refus qui comptent (non-participant, bloque, dormant)."""
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from realtime_messaging import store
from realtime_messaging.models import Block
from realtime_messaging.services import MessagingError, envoyer_message, ouvrir_conversation

User = get_user_model()


@pytest.fixture()
def alice(db):
    return User.objects.create_user(username="alice", password="x")


@pytest.fixture()
def bob(db):
    return User.objects.create_user(username="bob", password="x")


def test_conversation_idempotente_par_ref(faux_redis, alice, bob):
    cid1, created1 = ouvrir_conversation(demandeur=alice, participant_ids=[bob.id], ref="item:42")
    cid2, created2 = ouvrir_conversation(demandeur=alice, participant_ids=[bob.id], ref="item:42")
    assert created1 is True and created2 is False
    assert cid1 == cid2


def test_envoi_et_lecture(faux_redis, alice, bob):
    cid, _ = ouvrir_conversation(demandeur=alice, participant_ids=[bob.id])
    msg = envoyer_message(expediteur=alice, conv_id=cid, content="salut")
    assert msg["msg_type"] == "text" and msg["is_read"] is False

    inbox = store.list_user_conversations(bob.id)
    assert inbox[0]["unread_count"] == 1

    assert store.mark_conversation_read(cid, bob.id) == 1
    assert store.list_user_conversations(bob.id)[0]["unread_count"] == 0


def test_message_audio_porte_sa_duree(faux_redis, alice, bob):
    cid, _ = ouvrir_conversation(demandeur=alice, participant_ids=[bob.id])
    msg = envoyer_message(
        expediteur=alice, conv_id=cid,
        content="https://cdn.example/voix.webm", msg_type="audio", duration=42,
    )
    assert msg["duration"] == 42
    assert store.list_messages(cid)[0]["duration"] == 42


def test_non_participant_refuse(faux_redis, alice, bob, db):
    intrus = User.objects.create_user(username="intrus", password="x")
    cid, _ = ouvrir_conversation(demandeur=alice, participant_ids=[bob.id])
    with pytest.raises(MessagingError) as exc:
        envoyer_message(expediteur=intrus, conv_id=cid, content="coucou")
    assert exc.value.code == 403


def test_bloque_ne_peut_ni_ouvrir_ni_ecrire(faux_redis, alice, bob):
    cid, _ = ouvrir_conversation(demandeur=alice, participant_ids=[bob.id])
    Block.objects.create(blocker=bob, blocked=alice)
    with pytest.raises(MessagingError):
        envoyer_message(expediteur=alice, conv_id=cid, content="allo ?")
    with pytest.raises(MessagingError):
        ouvrir_conversation(demandeur=alice, participant_ids=[bob.id], ref="autre")


def test_reactions_et_suppression(faux_redis, alice, bob):
    cid, _ = ouvrir_conversation(demandeur=alice, participant_ids=[bob.id])
    msg = envoyer_message(expediteur=alice, conv_id=cid, content="vote ?")
    reactions = store.toggle_reaction(msg["id"], bob.id, "👍")
    assert reactions == {"👍": [str(bob.id)]}
    assert store.toggle_reaction(msg["id"], bob.id, "👍") == {}

    # seul l'expediteur supprime
    assert store.delete_message(msg["id"], bob.id) is None
    assert store.delete_message(msg["id"], alice.id) == cid
    assert store.list_messages(cid) == []


@pytest.mark.django_db
def test_api_dormante_sans_redis(settings, alice):
    settings.REALTIME_MESSAGING_REDIS_URL = ""
    settings.REDIS_URL = ""
    import os
    os.environ.pop("REALTIME_MESSAGING_REDIS_URL", None)
    os.environ.pop("REDIS_URL", None)
    client = APIClient()
    client.force_authenticate(alice)
    r = client.get("/api/messaging/conversations/")
    assert r.status_code == 503
    assert "dormant" in r.json()["detail"]


@pytest.mark.django_db
def test_api_envoi_bout_en_bout(faux_redis, alice, bob):
    client = APIClient()
    client.force_authenticate(alice)
    r = client.post("/api/messaging/conversations/", {"participant_ids": [bob.id]}, format="json")
    assert r.status_code == 201
    cid = r.json()["id"]
    r = client.post(
        f"/api/messaging/conversations/{cid}/messages/",
        {"content": "premier message"},
        format="json",
    )
    assert r.status_code == 201
    client.force_authenticate(bob)
    r = client.get(f"/api/messaging/conversations/{cid}/messages/")
    assert r.status_code == 200 and len(r.json()) == 1
