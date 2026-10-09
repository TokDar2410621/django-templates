"""Firebase HTTP v1 : la requete exacte envoyee a Google, et le traitement de ses reponses."""
import json

import httpx
import pytest

from push_notifications.backends import fcm
from push_notifications.models import PushDevice
from push_notifications.services import send_push

JETON_FCM = "fcm-jeton-de-test:APA91b" + "x" * 140


@pytest.fixture
def firebase(settings, monkeypatch, compte_service_google):
    """Branche Firebase sur un faux Google qui enregistre les requetes."""
    settings.PUSH_FCM_CREDENTIALS = compte_service_google
    etat = {"requetes": [], "reponse": (200, {"name": "projects/projet-test/messages/1"})}

    def repondre(requete: httpx.Request) -> httpx.Response:
        etat["requetes"].append(requete)
        statut, corps = etat["reponse"]
        return httpx.Response(statut, json=corps)

    monkeypatch.setattr(fcm, "_client", lambda: httpx.Client(transport=httpx.MockTransport(repondre)))
    monkeypatch.setattr(fcm, "_access_token", lambda: "jeton-oauth-test")
    return etat


def _appareil(user):
    return PushDevice.objects.create(user=user, kind="fcm", token=JETON_FCM)


def test_requete_v1_au_bon_format(firebase, alice):
    _appareil(alice)
    resultat = send_push(alice, "Nouvelle commande", "Commande #42", url="/commandes/42", data={"id": 42, "urgent": True})

    assert resultat.delivered == 1
    requete = firebase["requetes"][0]
    assert str(requete.url) == "https://fcm.googleapis.com/v1/projects/projet-test/messages:send"
    assert requete.headers["authorization"] == "Bearer jeton-oauth-test"
    message = json.loads(requete.content)["message"]
    assert message["token"] == JETON_FCM
    assert message["notification"] == {"title": "Nouvelle commande", "body": "Commande #42"}
    # Firebase refuse toute valeur non texte dans data : tout doit etre une chaine.
    assert message["data"] == {"id": "42", "urgent": "True", "url": "/commandes/42"}
    assert message["android"]["priority"] == "high"


def test_jeton_expire_est_supprime(firebase, alice):
    _appareil(alice)
    firebase["reponse"] = (404, {"error": {"code": 404, "status": "NOT_FOUND", "details": [{"errorCode": "UNREGISTERED"}]}})
    assert send_push(alice, "Bonjour").removed == 1
    assert not PushDevice.objects.exists()


def test_jeton_d_un_autre_projet_est_supprime(firebase, alice):
    _appareil(alice)
    firebase["reponse"] = (403, {"error": {"code": 403, "status": "PERMISSION_DENIED", "details": [{"errorCode": "SENDER_ID_MISMATCH"}]}})
    assert send_push(alice, "Bonjour").removed == 1


def test_requete_invalide_garde_l_appareil(firebase, alice):
    """Un 400 peut venir du message lui-meme : jamais une raison de supprimer l'appareil."""
    appareil = _appareil(alice)
    firebase["reponse"] = (400, {"error": {"code": 400, "status": "INVALID_ARGUMENT", "details": [{"errorCode": "INVALID_ARGUMENT"}]}})
    resultat = send_push(alice, "Bonjour")
    assert resultat.failed == 1
    appareil.refresh_from_db()
    assert appareil.last_error == "HTTP 400 INVALID_ARGUMENT"


def test_compte_de_service_lu_depuis_le_json_ou_un_fichier(settings, compte_service_google, tmp_path):
    settings.PUSH_FCM_CREDENTIALS = compte_service_google
    assert fcm._credentials().service_account_email == "push@projet-test.iam.gserviceaccount.com"
    assert fcm._project_id() == "projet-test"

    fcm.forget_credentials()
    fichier = tmp_path / "compte-service.json"
    fichier.write_text(compte_service_google, encoding="utf-8")
    settings.PUSH_FCM_CREDENTIALS = str(fichier)
    assert fcm._credentials().service_account_email == "push@projet-test.iam.gserviceaccount.com"


def test_sans_compte_de_service_rien_ne_part(alice):
    _appareil(alice)
    assert send_push(alice, "Bonjour").skipped == 1
    assert PushDevice.objects.count() == 1
