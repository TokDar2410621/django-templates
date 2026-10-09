"""Firebase Cloud Messaging, API HTTP v1 : Android, et iPhone si l'appli utilise le SDK Firebase.

L'ancienne API (cle serveur, https://fcm.googleapis.com/fcm/send) est
depreciee depuis le 20 juin 2023 et sa fermeture a commence le 22 juillet
2024 : tout code qui l'utilise encore n'envoie plus rien. L'API v1
s'authentifie avec un compte de service Google (fichier JSON).
Source : https://firebase.google.com/docs/cloud-messaging/migrate-v1
"""
from __future__ import annotations

import json
import logging
import threading

import httpx
from django.conf import settings

from .base import FAILED, GONE, OK, SKIPPED, PushMessage

logger = logging.getLogger(__name__)

SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_cache: dict = {"credentials": None}
_verrou = threading.Lock()


def configured() -> bool:
    return bool(getattr(settings, "PUSH_FCM_CREDENTIALS", ""))


def _service_account_info() -> dict:
    """PUSH_FCM_CREDENTIALS : le contenu du JSON du compte de service, ou le chemin du fichier."""
    valeur = settings.PUSH_FCM_CREDENTIALS.strip()
    if valeur.startswith("{"):
        return json.loads(valeur)
    with open(valeur, encoding="utf-8") as fichier:
        return json.load(fichier)


def _credentials():
    from google.oauth2 import service_account

    with _verrou:
        if _cache["credentials"] is None:
            _cache["credentials"] = service_account.Credentials.from_service_account_info(
                _service_account_info(), scopes=[SCOPE]
            )
        return _cache["credentials"]


def _access_token() -> str:
    from google.auth.transport.requests import Request

    credentials = _credentials()
    with _verrou:
        if not credentials.valid:
            credentials.refresh(Request())
        return credentials.token


def _project_id() -> str:
    return getattr(settings, "PUSH_FCM_PROJECT_ID", "") or _service_account_info()["project_id"]


def forget_credentials() -> None:
    with _verrou:
        _cache["credentials"] = None


def _client() -> httpx.Client:
    return httpx.Client(timeout=10)


def build_body(device, message: PushMessage) -> dict:
    return {
        "message": {
            "token": device.token,
            "notification": {"title": message.title, "body": message.body},
            "data": message.data_as_strings(),
            "android": {"priority": "high", "ttl": f"{message.ttl}s"},
            "apns": {"payload": {"aps": {"sound": "default"}}},
        }
    }


def _error_code(reponse: httpx.Response) -> str:
    try:
        erreur = reponse.json().get("error", {})
    except ValueError:
        return ""
    for detail in erreur.get("details", []) or []:
        if detail.get("errorCode"):
            return str(detail["errorCode"])
    return str(erreur.get("status", ""))


def send(device, message: PushMessage) -> tuple[str, str]:
    if not configured():
        return SKIPPED, "Firebase non configure"
    base = getattr(settings, "PUSH_FCM_BASE_URL", "https://fcm.googleapis.com").rstrip("/")
    try:
        url = f"{base}/v1/projects/{_project_id()}/messages:send"
        jeton = _access_token()
    except Exception as exc:  # compte de service illisible ou Google injoignable
        logger.error("Firebase : authentification impossible (%s)", type(exc).__name__)
        return FAILED, f"authentification Firebase : {type(exc).__name__}"
    try:
        with _client() as client:
            reponse = client.post(url, json=build_body(device, message), headers={"Authorization": f"Bearer {jeton}"})
    except httpx.HTTPError as exc:
        return FAILED, f"reseau : {type(exc).__name__}"

    if reponse.status_code == 200:
        return OK, ""
    code = _error_code(reponse)
    if reponse.status_code == 404 or code == "UNREGISTERED":
        return GONE, "jeton Firebase expire (UNREGISTERED)"
    if code == "SENDER_ID_MISMATCH":
        return GONE, "jeton d'un autre projet Firebase (SENDER_ID_MISMATCH)"
    if reponse.status_code in (401, 403):
        forget_credentials()
    logger.warning("Firebase refuse (HTTP %s, %s) pour l'appareil %s", reponse.status_code, code, device.pk)
    return FAILED, f"HTTP {reponse.status_code} {code}".strip()
