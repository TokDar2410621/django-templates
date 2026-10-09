import json

import httpx
import pytest

from push_notifications.backends import expo
from push_notifications.models import PushDevice
from push_notifications.services import send_push

JETON_EXPO = "ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx]"


@pytest.fixture
def serveur_expo(monkeypatch):
    etat = {"requetes": [], "reponse": (200, {"data": {"status": "ok", "id": "ticket-1"}})}

    def repondre(requete: httpx.Request) -> httpx.Response:
        etat["requetes"].append(requete)
        statut, corps = etat["reponse"]
        return httpx.Response(statut, json=corps)

    monkeypatch.setattr(expo, "_client", lambda: httpx.Client(transport=httpx.MockTransport(repondre)))
    return etat


def test_envoi_expo(serveur_expo, alice):
    PushDevice.objects.create(user=alice, kind="expo", token=JETON_EXPO)
    assert send_push(alice, "Bonjour", "Le corps", data={"id": 7}).delivered == 1
    corps = json.loads(serveur_expo["requetes"][0].content)
    assert corps["to"] == JETON_EXPO
    assert corps["data"] == {"id": "7"}


def test_appli_desinstallee_supprime_l_appareil(serveur_expo, alice):
    PushDevice.objects.create(user=alice, kind="expo", token=JETON_EXPO)
    serveur_expo["reponse"] = (200, {"data": {"status": "error", "details": {"error": "DeviceNotRegistered"}}})
    assert send_push(alice, "Bonjour").removed == 1


def test_panne_expo_garde_l_appareil(serveur_expo, alice):
    PushDevice.objects.create(user=alice, kind="expo", token=JETON_EXPO)
    serveur_expo["reponse"] = (503, {})
    assert send_push(alice, "Bonjour").failed == 1
    assert PushDevice.objects.count() == 1
