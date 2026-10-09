"""Apple Push Notification service en direct : iPhone, quand l'appli n'utilise pas Firebase.

Reprend des lecons vecues en production :
- le jeton fournisseur (JWT ES256) se garde 50 minutes : Apple refuse un jeton
  de plus de 60 minutes et un renouvellement plus d'une fois par 20 minutes ;
- un build Xcode parle au serveur sandbox, TestFlight et l'App Store au serveur
  de production : sur BadDeviceToken, on reessaie une fois en sandbox ;
- une cle .p8 collee sur une ligne dans une variable porte des \\n litteraux.
"""
from __future__ import annotations

import logging
import threading
import time

import httpx
import jwt
from django.conf import settings

from .base import FAILED, GONE, OK, SKIPPED, PushMessage

logger = logging.getLogger(__name__)

HOST_PRODUCTION = "https://api.push.apple.com"
HOST_SANDBOX = "https://api.sandbox.push.apple.com"
TOKEN_LIFETIME = 50 * 60

_cache: dict = {"value": None, "issued_at": 0.0}
_verrou = threading.Lock()


def configured() -> bool:
    return all(
        getattr(settings, nom, "")
        for nom in ("PUSH_APNS_TEAM_ID", "PUSH_APNS_KEY_ID", "PUSH_APNS_AUTH_KEY", "PUSH_APNS_BUNDLE_ID")
    )


def _private_key() -> str:
    return settings.PUSH_APNS_AUTH_KEY.replace("\\n", "\n").strip() + "\n"


def provider_token() -> str:
    maintenant = time.time()
    with _verrou:
        if _cache["value"] and maintenant - _cache["issued_at"] < TOKEN_LIFETIME:
            return _cache["value"]
        valeur = jwt.encode(
            {"iss": settings.PUSH_APNS_TEAM_ID, "iat": int(maintenant)},
            _private_key(),
            algorithm="ES256",
            headers={"kid": settings.PUSH_APNS_KEY_ID},
        )
        _cache["value"], _cache["issued_at"] = valeur, maintenant
        return valeur


def forget_token() -> None:
    with _verrou:
        _cache["value"], _cache["issued_at"] = None, 0.0


def _client() -> httpx.Client:
    return httpx.Client(http2=True, timeout=10)  # Apple exige HTTP/2


def _reason(reponse: httpx.Response) -> str:
    try:
        return str((reponse.json() or {}).get("reason", ""))
    except ValueError:
        return ""


def _post(device, message: PushMessage) -> httpx.Response:
    host = HOST_SANDBOX if device.apns_sandbox else HOST_PRODUCTION
    headers = {
        "authorization": f"bearer {provider_token()}",
        "apns-topic": settings.PUSH_APNS_BUNDLE_ID,
        "apns-push-type": "alert",
        "apns-priority": "10",
        "apns-expiration": str(int(time.time()) + message.ttl),
    }
    corps = {"aps": {"alert": {"title": message.title, "body": message.body}, "sound": "default"}}
    corps.update(message.data_as_strings())
    with _client() as client:
        return client.post(f"{host}/3/device/{device.token}", headers=headers, json=corps)


def send(device, message: PushMessage) -> tuple[str, str]:
    if not configured():
        return SKIPPED, "APNs non configure"
    for tentative in (1, 2):
        try:
            reponse = _post(device, message)
        except httpx.HTTPError as exc:
            return FAILED, f"reseau : {type(exc).__name__}"
        except (jwt.PyJWTError, ValueError) as exc:
            logger.error("APNs : cle .p8 illisible (%s)", type(exc).__name__)
            return FAILED, "cle APNs illisible"

        if reponse.status_code == 200:
            return OK, ""
        raison = _reason(reponse)
        if reponse.status_code == 400 and raison == "BadDeviceToken":
            if not device.apns_sandbox and tentative == 1:
                type(device).objects.filter(pk=device.pk).update(apns_sandbox=True)
                device.apns_sandbox = True
                continue
            return GONE, "BadDeviceToken en production et en sandbox"
        if reponse.status_code == 410:
            return GONE, "appli desinstallee (Unregistered)"
        if reponse.status_code == 403:
            forget_token()
            logger.error("APNs refuse le jeton fournisseur (%s) : verifier TEAM_ID, KEY_ID et la cle .p8", raison)
        return FAILED, f"HTTP {reponse.status_code} {raison}".strip()
    return FAILED, "APNs : echec apres deux tentatives"
