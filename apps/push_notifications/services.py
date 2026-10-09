"""Envoyer un push : la seule fonction a appeler depuis ton code.

    from push_notifications.services import send_push
    resultat = send_push(user, "Nouvelle commande", "Commande #42 recue", url="/commandes/42", data={"id": 42})

Le push part vers TOUS les appareils de l'utilisateur (navigateurs, Android,
iPhone). Les appareils morts sont supprimes, les erreurs notees sur l'appareil.
L'envoi est synchrone (un appel HTTP par appareil) : depuis une vue tres
frequentee, lance-le dans une tache de fond (Celery, django-q, thread).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.utils import timezone

from . import selectors
from .backends import BACKENDS
from .backends.base import FAILED, GONE, OK, PushMessage
from .models import PushDevice, empreinte

logger = logging.getLogger(__name__)


@dataclass
class PushResult:
    delivered: int = 0
    removed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "delivered": self.delivered,
            "removed": self.removed,
            "failed": self.failed,
            "skipped": self.skipped,
            "errors": self.errors,
        }


def send_push(user, title: str, body: str = "", *, url: str = "", data: dict | None = None) -> PushResult:
    """Pousse un message a tous les appareils de l'utilisateur. Ne leve jamais."""
    message = PushMessage(title=title, body=body, url=url, data=data or {})
    resultat = PushResult()
    for device in list(selectors.devices_for_user(user)):
        backend = BACKENDS.get(device.kind)
        if backend is None:
            resultat.skipped += 1
            continue
        try:
            statut, detail = backend.send(device, message)
        except Exception as exc:  # un fournisseur ne doit jamais casser l'appelant
            logger.exception("Push : erreur inattendue pour l'appareil %s", device.pk)
            statut, detail = FAILED, f"erreur inattendue : {type(exc).__name__}"

        if statut == OK:
            resultat.delivered += 1
            PushDevice.objects.filter(pk=device.pk).update(last_used_at=timezone.now(), last_error="")
        elif statut == GONE:
            resultat.removed += 1
            logger.info("Push : appareil %s supprime (%s)", device.pk, detail)
            PushDevice.objects.filter(pk=device.pk).delete()
        elif statut == FAILED:
            resultat.failed += 1
            resultat.errors.append(f"{device.kind} : {detail}")
            PushDevice.objects.filter(pk=device.pk).update(last_error=detail[:255])
        else:
            resultat.skipped += 1
            resultat.errors.append(f"{device.kind} : {detail}")
    return resultat


def register_device(
    user, kind: str, token: str, *, p256dh: str = "", auth: str = "", apns_sandbox: bool = False
) -> PushDevice:
    """Enregistre un appareil, ou le rattache a cet utilisateur s'il existait deja.

    Un meme jeton ne cree jamais deux lignes : un telephone qui change de
    compte passe simplement au nouvel utilisateur.
    """
    device, _ = PushDevice.objects.update_or_create(
        token_hash=empreinte(token),
        defaults={
            "user": user,
            "kind": kind,
            "token": token.strip(),
            "p256dh": p256dh,
            "auth": auth,
            "apns_sandbox": apns_sandbox,
            "last_error": "",
        },
    )
    return device


def unregister_device(user, token: str) -> int:
    """Retire un appareil de CET utilisateur (deconnexion, refus des notifications)."""
    supprimes, _ = selectors.device_for_token(user, token).delete()
    return supprimes
