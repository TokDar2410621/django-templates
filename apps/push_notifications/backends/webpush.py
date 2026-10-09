"""Web Push (navigateurs : Chrome, Firefox, Edge, Safari, PWA sur iPhone) via pywebpush et VAPID."""
from __future__ import annotations

import json
import logging

from django.conf import settings

from ..cles import private_key_for_pywebpush
from .base import FAILED, GONE, OK, SKIPPED, PushMessage

logger = logging.getLogger(__name__)


def configured() -> bool:
    return bool(
        getattr(settings, "PUSH_VAPID_PUBLIC_KEY", "")
        and getattr(settings, "PUSH_VAPID_PRIVATE_KEY", "")
        and getattr(settings, "PUSH_VAPID_CONTACT", "")
    )


def _contact() -> str:
    contact = settings.PUSH_VAPID_CONTACT.strip()
    return contact if contact.startswith(("mailto:", "https://")) else f"mailto:{contact}"


def send(device, message: PushMessage) -> tuple[str, str]:
    if not configured():
        return SKIPPED, "VAPID non configure"
    from pywebpush import WebPushException, webpush
    from requests import RequestException

    payload = json.dumps(
        {"title": message.title, "body": message.body, "url": message.url, "data": message.data_as_strings()}
    )
    try:
        webpush(
            subscription_info={"endpoint": device.token, "keys": {"p256dh": device.p256dh, "auth": device.auth}},
            data=payload,
            vapid_private_key=private_key_for_pywebpush(settings.PUSH_VAPID_PRIVATE_KEY),
            # Un dictionnaire NEUF a chaque envoi : pywebpush y ecrit l'adresse du
            # service de push ("aud"). Partage entre envois, il garderait celle du
            # premier navigateur et les autres refuseraient (403).
            vapid_claims={"sub": _contact()},
            ttl=message.ttl,
            timeout=10,
        )
    except WebPushException as exc:
        code = getattr(getattr(exc, "response", None), "status_code", None)
        if code in (404, 410):
            return GONE, f"abonnement expire ({code})"
        logger.warning("Web Push refuse (HTTP %s) pour l'appareil %s", code, device.pk)
        return FAILED, f"HTTP {code}"
    except RequestException as exc:
        logger.warning("Web Push injoignable pour l'appareil %s : %s", device.pk, type(exc).__name__)
        return FAILED, f"reseau : {type(exc).__name__}"
    except ValueError as exc:
        # Cle VAPID illisible : erreur de configuration, pas de l'appareil.
        logger.error("Cle VAPID illisible : %s", exc)
        return FAILED, "cle VAPID illisible"
    return OK, ""
