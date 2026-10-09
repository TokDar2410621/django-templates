"""Expo Push : pour une appli React Native construite avec Expo (jetons ExponentPushToken[...])."""
from __future__ import annotations

import httpx
from django.conf import settings

from .base import FAILED, GONE, OK, PushMessage

URL = "https://exp.host/--/api/v2/push/send"


def configured() -> bool:
    return True  # aucune cle requise ; PUSH_EXPO_ACCESS_TOKEN si la securite renforcee est activee chez Expo


def _client() -> httpx.Client:
    return httpx.Client(timeout=10)


def send(device, message: PushMessage) -> tuple[str, str]:
    headers = {"Accept": "application/json"}
    access = getattr(settings, "PUSH_EXPO_ACCESS_TOKEN", "")
    if access:
        headers["Authorization"] = f"Bearer {access}"
    corps = {
        "to": device.token,
        "title": message.title,
        "body": message.body,
        "data": message.data_as_strings(),
        "sound": "default",
        "ttl": message.ttl,
    }
    try:
        with _client() as client:
            reponse = client.post(getattr(settings, "PUSH_EXPO_URL", URL), json=corps, headers=headers)
    except httpx.HTTPError as exc:
        return FAILED, f"reseau : {type(exc).__name__}"
    if reponse.status_code != 200:
        return FAILED, f"HTTP {reponse.status_code}"
    try:
        ticket = reponse.json().get("data", {})
    except ValueError:
        return FAILED, "reponse Expo illisible"
    if isinstance(ticket, list):
        ticket = ticket[0] if ticket else {}
    if ticket.get("status") == "ok":
        return OK, ""
    erreur = (ticket.get("details") or {}).get("error", "")
    if erreur == "DeviceNotRegistered":
        return GONE, "appli desinstallee (DeviceNotRegistered)"
    return FAILED, f"Expo : {erreur or ticket.get('message', 'erreur')}"[:255]
