"""Apple direct : jeton fournisseur signe, bascule sandbox, appareils morts."""
import json

import httpx
import jwt
import pytest

from push_notifications.backends import apns
from push_notifications.models import PushDevice
from push_notifications.services import send_push

JETON_IPHONE = "a1" * 32


@pytest.fixture
def apple(settings, monkeypatch, cle_p8):
    settings.PUSH_APNS_TEAM_ID = "EQUIPE1234"
    settings.PUSH_APNS_KEY_ID = "CLE5678"
    settings.PUSH_APNS_AUTH_KEY = cle_p8["pem"].replace("\n", "\\n")  # collee sur une ligne
    settings.PUSH_APNS_BUNDLE_ID = "com.exemple.appli"
    etat = {"requetes": [], "repondre": lambda requete: (200, {})}

    def repondre(requete: httpx.Request) -> httpx.Response:
        etat["requetes"].append(requete)
        statut, corps = etat["repondre"](requete)
        return httpx.Response(statut, json=corps)

    monkeypatch.setattr(apns, "_client", lambda: httpx.Client(transport=httpx.MockTransport(repondre)))
    etat["publique"] = cle_p8["publique"]
    return etat


def _appareil(user, sandbox=False):
    return PushDevice.objects.create(user=user, kind="apns", token=JETON_IPHONE, apns_sandbox=sandbox)


def test_requete_signee_au_bon_format(apple, alice):
    _appareil(alice)
    assert send_push(alice, "Nouvelle commande", "Commande #42", data={"id": 42}).delivered == 1

    requete = apple["requetes"][0]
    assert str(requete.url) == f"https://api.push.apple.com/3/device/{JETON_IPHONE}"
    assert requete.headers["apns-topic"] == "com.exemple.appli"
    assert requete.headers["apns-push-type"] == "alert"
    jeton = requete.headers["authorization"].removeprefix("bearer ")
    assert jwt.get_unverified_header(jeton)["kid"] == "CLE5678"
    assert jwt.decode(jeton, apple["publique"], algorithms=["ES256"])["iss"] == "EQUIPE1234"
    corps = json.loads(requete.content)
    assert corps["aps"]["alert"] == {"title": "Nouvelle commande", "body": "Commande #42"}
    assert corps["id"] == "42"


def test_le_jeton_fournisseur_est_reutilise(apple, alice):
    _appareil(alice)
    send_push(alice, "Un")
    send_push(alice, "Deux")
    premiers, seconds = (r.headers["authorization"] for r in apple["requetes"])
    assert premiers == seconds


def test_build_xcode_bascule_en_sandbox_puis_reussit(apple, alice):
    apple["repondre"] = lambda requete: (
        (200, {}) if requete.url.host == "api.sandbox.push.apple.com" else (400, {"reason": "BadDeviceToken"})
    )
    appareil = _appareil(alice)
    assert send_push(alice, "Bonjour").delivered == 1
    appareil.refresh_from_db()
    assert appareil.apns_sandbox is True


def test_bad_device_token_partout_supprime_l_appareil(apple, alice):
    apple["repondre"] = lambda requete: (400, {"reason": "BadDeviceToken"})
    _appareil(alice)
    assert send_push(alice, "Bonjour").removed == 1
    assert not PushDevice.objects.exists()


def test_appli_desinstallee_supprime_l_appareil(apple, alice):
    apple["repondre"] = lambda requete: (410, {"reason": "Unregistered"})
    _appareil(alice)
    assert send_push(alice, "Bonjour").removed == 1


def test_jeton_fournisseur_refuse_est_oublie(apple, alice):
    apple["repondre"] = lambda requete: (403, {"reason": "InvalidProviderToken"})
    _appareil(alice)
    resultat = send_push(alice, "Bonjour")
    assert resultat.failed == 1
    assert apns._cache["value"] is None
    assert PushDevice.objects.count() == 1
