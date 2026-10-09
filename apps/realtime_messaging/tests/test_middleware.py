# -*- coding: utf-8 -*-
"""JWTAuthMiddleware : le jeton authentifie, et son absence ne deconnecte jamais une session."""
from __future__ import annotations

import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import AccessToken

from realtime_messaging.middleware import JWTAuthMiddleware


def _utilisateur_vu(scope: dict):
    """Fait passer un scope dans le middleware et rend le scope['user'] recu par l'appli."""
    vu: dict = {}

    async def appli(scope, receive, send):
        vu["user"] = scope.get("user")

    async def recevoir():
        return {}

    async def envoyer(message):
        return None

    async_to_sync(JWTAuthMiddleware(appli))(scope, recevoir, envoyer)
    return vu["user"]


@pytest.mark.django_db(transaction=True)
def test_jeton_valide_authentifie():
    alice = get_user_model().objects.create_user(username="alice-ws", password="mot-de-passe-test")
    jeton = str(AccessToken.for_user(alice))
    user = _utilisateur_vu({"type": "websocket", "query_string": f"token={jeton}".encode()})
    assert user.pk == alice.pk


@pytest.mark.django_db(transaction=True)
def test_jeton_invalide_donne_un_anonyme():
    user = _utilisateur_vu({"type": "websocket", "query_string": b"token=pas-un-jwt"})
    assert not user.is_authenticated


def test_sans_jeton_la_session_deja_posee_est_gardee():
    """Empile sous AuthMiddlewareStack : l'utilisateur de session ne doit pas devenir anonyme."""

    class UtilisateurDeSession:
        is_authenticated = True

    session = UtilisateurDeSession()
    user = _utilisateur_vu({"type": "websocket", "query_string": b"", "user": session})
    assert user is session


def test_sans_jeton_ni_session_donne_un_anonyme():
    user = _utilisateur_vu({"type": "websocket", "query_string": b""})
    assert not user.is_authenticated
