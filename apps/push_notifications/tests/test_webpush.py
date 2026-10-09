"""Web Push sans aucun faux : chiffrement reel, signature VAPID reelle, dechiffrement cote navigateur."""
import base64
import json
import re

import http_ece
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from push_notifications.cles import generate_vapid_keys
from push_notifications.models import PushDevice
from push_notifications.services import send_push
from .conftest import FauxServiceDePush


def _decode(valeur: str) -> bytes:
    return base64.urlsafe_b64decode(valeur + "=" * (-len(valeur) % 4))


def _poser_vapid(settings, format_cle: str = "brute") -> str:
    publique, privee = generate_vapid_keys()
    if format_cle != "brute":
        cle = ec.derive_private_key(int.from_bytes(_decode(privee), "big"), ec.SECP256R1())
        privee = cle.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ).decode()
        if format_cle == "pem_une_ligne":
            privee = privee.replace("\n", "\\n")  # comme une variable d'environnement collee sur une ligne
    settings.PUSH_VAPID_PUBLIC_KEY = publique
    settings.PUSH_VAPID_PRIVATE_KEY = privee
    settings.PUSH_VAPID_CONTACT = "admin@exemple.com"
    return publique


def _abonner(user, service, abonne) -> PushDevice:
    return PushDevice.objects.create(
        user=user, kind="web", token=f"{service.url}/push/abonnement-1", p256dh=abonne["p256dh"], auth=abonne["auth"]
    )


def _lire(recu: dict, abonne: dict) -> dict:
    clair = http_ece.decrypt(
        recu["corps"], private_key=abonne["cle_privee"], auth_secret=abonne["secret"], version="aes128gcm"
    )
    return json.loads(clair)


def _jwt_vapid(recu: dict) -> tuple[str, str]:
    entetes = {k.lower(): v for k, v in recu["headers"].items()}
    autorisation = entetes["authorization"]
    return re.search(r"t=([^,\s]+)", autorisation).group(1), re.search(r"k=([^,\s]+)", autorisation).group(1)


@pytest.mark.parametrize("format_cle", ["brute", "pem", "pem_une_ligne"])
def test_le_navigateur_dechiffre_le_message_quel_que_soit_le_format_de_cle(settings, alice, service_push, abonne, format_cle):
    publique = _poser_vapid(settings, format_cle)
    _abonner(alice, service_push, abonne)

    resultat = send_push(alice, "Nouvelle commande", "Commande #42", url="/commandes/42", data={"id": 42})

    assert resultat.delivered == 1, resultat.errors
    recu = service_push.recus[0]
    assert _lire(recu, abonne) == {
        "title": "Nouvelle commande",
        "body": "Commande #42",
        "url": "/commandes/42",
        "data": {"id": "42", "url": "/commandes/42"},
    }
    jeton, k = _jwt_vapid(recu)
    assert k == publique
    cle_publique = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), _decode(publique))
    revendications = jwt.decode(jeton, cle_publique, algorithms=["ES256"], audience=service_push.url)
    assert revendications["sub"] == "mailto:admin@exemple.com"


def test_deux_navigateurs_sur_deux_services_recoivent_chacun_leur_signature(settings, alice, abonne):
    """Le piege du dictionnaire vapid_claims partage : chaque service doit recevoir SON adresse (aud)."""
    _poser_vapid(settings)
    chrome, firefox = FauxServiceDePush(), FauxServiceDePush()
    try:
        _abonner(alice, chrome, abonne)
        PushDevice.objects.create(
            user=alice, kind="web", token=f"{firefox.url}/push/2", p256dh=abonne["p256dh"], auth=abonne["auth"]
        )
        assert send_push(alice, "Bonjour").delivered == 2
        for service in (chrome, firefox):
            jeton, _ = _jwt_vapid(service.recus[0])
            assert jwt.decode(jeton, options={"verify_signature": False})["aud"] == service.url
    finally:
        chrome.fermer()
        firefox.fermer()


@pytest.mark.parametrize("statut", [404, 410])
def test_abonnement_expire_est_supprime(settings, alice, service_push, abonne, statut):
    _poser_vapid(settings)
    _abonner(alice, service_push, abonne)
    service_push.statut = statut
    resultat = send_push(alice, "Bonjour")
    assert resultat.removed == 1
    assert not PushDevice.objects.exists()


def test_panne_du_service_garde_l_abonnement_et_note_l_erreur(settings, alice, service_push, abonne):
    _poser_vapid(settings)
    appareil = _abonner(alice, service_push, abonne)
    service_push.statut = 500
    resultat = send_push(alice, "Bonjour")
    assert resultat.failed == 1
    appareil.refresh_from_db()
    assert appareil.last_error == "HTTP 500"


def test_sans_cles_vapid_rien_ne_part_et_rien_n_est_supprime(alice, service_push, abonne):
    _abonner(alice, service_push, abonne)
    resultat = send_push(alice, "Bonjour")
    assert resultat.skipped == 1
    assert service_push.recus == []
    assert PushDevice.objects.count() == 1
