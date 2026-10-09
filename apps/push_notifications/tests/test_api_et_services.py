import io
import json

import httpx
import pytest
from django.core.management import call_command
from py_vapid import Vapid
from rest_framework.test import APIClient

from push_notifications.backends import expo
from push_notifications.cles import generate_vapid_keys, private_key_for_pywebpush, public_key_is_valid
from push_notifications.models import PushDevice
from push_notifications.services import send_push

ABONNEMENT = {
    "endpoint": "https://fcm.googleapis.com/fcm/send/abc123",
    "keys": {"p256dh": "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QTpQtUbVlUls0VJXg7A8u-Ts1XbjhazAkj7I99e8QcYP7DkM", "auth": "tBHItJI5svbpez7KI4CCXg"},
}


def _client(user=None) -> APIClient:
    client = APIClient()
    if user:
        client.force_authenticate(user)
    return client


@pytest.fixture
def expo_ok(monkeypatch):
    envoyes = []

    def repondre(requete):
        envoyes.append(json.loads(requete.content)["to"])
        return httpx.Response(200, json={"data": {"status": "ok"}})

    monkeypatch.setattr(expo, "_client", lambda: httpx.Client(transport=httpx.MockTransport(repondre)))
    return envoyes


# --- Cles VAPID --------------------------------------------------------------

def test_cles_generees_valides_et_lisibles_par_pywebpush():
    publique, privee = generate_vapid_keys()
    assert public_key_is_valid(publique)
    assert not public_key_is_valid("pas-une-cle")
    Vapid.from_string(private_key_for_pywebpush(privee))


def test_commande_generer_cles_vapid():
    sortie = io.StringIO()
    call_command("generer_cles_vapid", stdout=sortie)
    lignes = dict(l.split("=", 1) for l in sortie.getvalue().splitlines() if l.startswith("PUSH_VAPID_"))
    assert public_key_is_valid(lignes["PUSH_VAPID_PUBLIC_KEY"])
    Vapid.from_string(private_key_for_pywebpush(lignes["PUSH_VAPID_PRIVATE_KEY"]))


# --- API -------------------------------------------------------------------

def test_cle_publique_accessible_sans_connexion(settings, db):
    settings.PUSH_VAPID_PUBLIC_KEY = "CLE-PUBLIQUE"
    assert _client().get("/api/push/cle-vapid/").json() == {"public_key": "CLE-PUBLIQUE"}


def test_enregistrer_exige_une_connexion(db):
    reponse = _client().post("/api/push/appareils/", {"kind": "fcm", "token": "x" * 40}, format="json")
    assert reponse.status_code in (401, 403)


def test_enregistrer_un_navigateur(alice):
    reponse = _client(alice).post("/api/push/appareils/", {"kind": "web", "subscription": ABONNEMENT}, format="json")
    assert reponse.status_code == 201
    appareil = PushDevice.objects.get()
    assert (appareil.kind, appareil.token, appareil.auth) == ("web", ABONNEMENT["endpoint"], "tBHItJI5svbpez7KI4CCXg")


def test_un_endpoint_non_https_est_refuse(alice):
    abonnement = dict(ABONNEMENT, endpoint="http://exemple.com/push")
    reponse = _client(alice).post("/api/push/appareils/", {"kind": "web", "subscription": abonnement}, format="json")
    assert reponse.status_code == 400


def test_un_meme_jeton_change_de_compte_sans_doublon(alice, bob):
    for user in (alice, bob):
        assert _client(user).post("/api/push/appareils/", {"kind": "fcm", "token": "jeton-" + "x" * 40}, format="json").status_code == 201
    appareil = PushDevice.objects.get()
    assert appareil.user == bob


@pytest.mark.parametrize(
    "corps",
    [
        {"kind": "expo", "token": "pas-un-jeton-expo"},
        {"kind": "apns", "token": "pas-hexadecimal"},
        {"kind": "fcm"},
        {"kind": "web"},
        {"kind": "pigeon", "token": "x"},
    ],
)
def test_corps_invalides_refuses(alice, corps):
    assert _client(alice).post("/api/push/appareils/", corps, format="json").status_code == 400


def test_on_ne_retire_que_ses_propres_appareils(alice, bob):
    _client(alice).post("/api/push/appareils/", {"kind": "fcm", "token": "jeton-" + "y" * 40}, format="json")
    assert _client(bob).delete("/api/push/appareils/", {"token": "jeton-" + "y" * 40}, format="json").status_code == 404
    assert _client(alice).delete("/api/push/appareils/", {"token": "jeton-" + "y" * 40}, format="json").status_code == 204


def test_push_de_test_rend_le_diagnostic(alice, expo_ok):
    PushDevice.objects.create(user=alice, kind="expo", token="ExponentPushToken[aaa]")
    corps = _client(alice).post("/api/push/test/").json()
    assert corps["result"]["delivered"] == 1
    assert corps["devices"][0]["kind"] == "expo"


# --- Services ----------------------------------------------------------------

def test_le_push_ne_part_que_vers_les_appareils_du_destinataire(alice, bob, expo_ok):
    PushDevice.objects.create(user=alice, kind="expo", token="ExponentPushToken[alice]")
    PushDevice.objects.create(user=bob, kind="expo", token="ExponentPushToken[bob]")
    assert send_push(alice, "Bonjour").delivered == 1
    assert expo_ok == ["ExponentPushToken[alice]"]


def test_un_fournisseur_qui_plante_ne_casse_pas_l_appelant(alice, monkeypatch):
    PushDevice.objects.create(user=alice, kind="expo", token="ExponentPushToken[aaa]")

    def plante(device, message):
        raise RuntimeError("boum")

    monkeypatch.setattr(expo, "send", plante)
    resultat = send_push(alice, "Bonjour")
    assert resultat.failed == 1
    assert "RuntimeError" in resultat.errors[0]
