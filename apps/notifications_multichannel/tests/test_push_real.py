"""Web Push end to end, WITHOUT mocking pywebpush.

A local HTTP server plays the browser's push service. The test checks what a
real browser would: the payload decrypts with the subscriber's keys and the
VAPID signature verifies. The mocked tests (test_push.py) never caught that
a PEM key broke every real send in 1.0.0.
"""
from __future__ import annotations

import base64
import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import http_ece
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from notifications_multichannel.models import PushSubscription
from notifications_multichannel.services import send_push

from .conftest import generate_vapid_pem


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class LocalPushService:
    """A real HTTP server standing in for Mozilla / Google push services."""

    def __init__(self):
        self.received: list[dict] = []
        self.status = 201
        service = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                service.received.append(
                    {"headers": {k.lower(): v for k, v in self.headers.items()}, "body": self.rfile.read(length)}
                )
                self.send_response(service.status)
                self.end_headers()

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()


@pytest.fixture
def push_service():
    service = LocalPushService()
    yield service
    service.close()


@pytest.fixture
def subscriber():
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    secret = os.urandom(16)
    return {"key": key, "p256dh": _b64url(public), "auth": _b64url(secret), "secret": secret}


def _configure(settings, key_format: str) -> str:
    public, pem = generate_vapid_pem()
    if key_format == "pem_single_line":
        private = pem.replace("\n", "\\n")
    elif key_format == "raw":
        key = serialization.load_pem_private_key(pem.encode(), password=None)
        private = _b64url(key.private_numbers().private_value.to_bytes(32, "big"))
    else:
        private = pem
    settings.VAPID_PUBLIC_KEY = public
    settings.VAPID_PRIVATE_KEY = private
    settings.VAPID_ADMIN_EMAIL = "admin@example.com"
    return public


@pytest.mark.django_db
@pytest.mark.parametrize("key_format", ["pem", "pem_single_line", "raw"])
def test_browser_decrypts_payload_and_verifies_signature(settings, user, push_service, subscriber, key_format):
    public = _configure(settings, key_format)
    PushSubscription.objects.create(
        user=user, endpoint=f"{push_service.url}/push/1", p256dh=subscriber["p256dh"], auth=subscriber["auth"]
    )

    result = send_push(user=user, title="Order", body="Order #42", url="/orders/42")

    assert result.status == "sent", result.error
    received = push_service.received[0]
    clear = http_ece.decrypt(
        received["body"], private_key=subscriber["key"], auth_secret=subscriber["secret"], version="aes128gcm"
    )
    assert json.loads(clear)["title"] == "Order"
    authorization = received["headers"]["authorization"]
    token = re.search(r"t=([^,\s]+)", authorization).group(1)
    assert re.search(r"k=([^,\s]+)", authorization).group(1) == public
    vapid_public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), _b64url_decode(public))
    claims = jwt.decode(token, vapid_public, algorithms=["ES256"], audience=push_service.url)
    assert claims["sub"] == "mailto:admin@example.com"


@pytest.mark.django_db
@pytest.mark.parametrize("status", [404, 410])
def test_gone_subscription_is_pruned(settings, user, push_service, subscriber, status):
    _configure(settings, "pem")
    PushSubscription.objects.create(
        user=user, endpoint=f"{push_service.url}/push/1", p256dh=subscriber["p256dh"], auth=subscriber["auth"]
    )
    push_service.status = status
    result = send_push(user=user, title="Hi", body="")
    assert result.meta["pruned"] == 1
    assert not PushSubscription.objects.filter(user=user).exists()
