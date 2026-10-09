import base64
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.contrib.auth import get_user_model

from push_notifications.backends import apns, fcm


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


@pytest.fixture(autouse=True)
def caches_vides():
    """Les jetons fournisseurs sont gardes en memoire : chaque test repart de zero."""
    apns.forget_token()
    fcm.forget_credentials()
    yield
    apns.forget_token()
    fcm.forget_credentials()


@pytest.fixture
def alice(db):
    return get_user_model().objects.create_user(username="alice", password="mot-de-passe-test")


@pytest.fixture
def bob(db):
    return get_user_model().objects.create_user(username="bob", password="mot-de-passe-test")


class FauxServiceDePush:
    """Un vrai serveur HTTP local qui joue le service de push d'un navigateur."""

    def __init__(self):
        self.recus: list[dict] = []
        self.statut = 201
        service = self

        class Gestionnaire(BaseHTTPRequestHandler):
            def do_POST(self):
                longueur = int(self.headers.get("Content-Length", 0))
                service.recus.append({"headers": dict(self.headers), "corps": self.rfile.read(longueur), "chemin": self.path})
                self.send_response(service.statut)
                self.end_headers()

            def log_message(self, *args):
                pass

        self.serveur = HTTPServer(("127.0.0.1", 0), Gestionnaire)
        self.url = f"http://127.0.0.1:{self.serveur.server_port}"
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()

    def fermer(self):
        self.serveur.shutdown()


@pytest.fixture
def service_push():
    service = FauxServiceDePush()
    yield service
    service.fermer()


@pytest.fixture
def abonne():
    """Les cles d'un navigateur abonne : de quoi dechiffrer ce qu'il recoit."""
    cle = ec.generate_private_key(ec.SECP256R1())
    publique = cle.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    secret = os.urandom(16)
    return {"cle_privee": cle, "p256dh": b64url(publique), "auth": b64url(secret), "secret": secret}


@pytest.fixture
def cle_p8():
    """Une cle .p8 Apple de test (EC P-256 au format PEM)."""
    cle = ec.generate_private_key(ec.SECP256R1())
    pem = cle.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    return {"pem": pem, "publique": cle.public_key()}


@pytest.fixture
def compte_service_google():
    """Un JSON de compte de service Google de test (cle RSA generee)."""
    from cryptography.hazmat.primitives.asymmetric import rsa

    cle = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = cle.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    return json.dumps(
        {
            "type": "service_account",
            "project_id": "projet-test",
            "private_key_id": "abc123",
            "private_key": pem,
            "client_email": "push@projet-test.iam.gserviceaccount.com",
            "client_id": "1234567890",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )
