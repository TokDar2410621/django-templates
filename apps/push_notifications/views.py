"""API : l'appli et le site y enregistrent leurs appareils.

Elle utilise l'authentification DRF du projet (session, JWT, jeton...) : rien a configurer ici.
"""
from __future__ import annotations

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import selectors, services
from .models import PushDevice
from .serializers import DeviceSerializer, UnregisterSerializer


class VapidPublicKeyView(APIView):
    """GET : la cle publique VAPID dont le navigateur a besoin pour s'abonner."""

    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"public_key": getattr(settings, "PUSH_VAPID_PUBLIC_KEY", "")})


class DeviceView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = DeviceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        donnees = serializer.validated_data
        if donnees["kind"] == PushDevice.WEB:
            abonnement = donnees["subscription"]
            device = services.register_device(
                request.user,
                PushDevice.WEB,
                abonnement["endpoint"],
                p256dh=abonnement["keys"]["p256dh"],
                auth=abonnement["keys"]["auth"],
            )
        else:
            device = services.register_device(
                request.user, donnees["kind"], donnees["token"], apns_sandbox=donnees.get("sandbox", False)
            )
        return Response({"id": device.pk, "kind": device.kind}, status=status.HTTP_201_CREATED)

    def delete(self, request):
        serializer = UnregisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        supprimes = services.unregister_device(request.user, serializer.validated_data["token"])
        return Response(status=status.HTTP_204_NO_CONTENT if supprimes else status.HTTP_404_NOT_FOUND)


class TestPushView(APIView):
    """POST : s'envoyer un push de test et voir, appareil par appareil, ce qui a coince."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        resultat = services.send_push(
            request.user, "Test de notification", "Si tu lis ceci, le push marche.", url="/"
        )
        return Response({"result": resultat.as_dict(), "devices": selectors.device_summaries(request.user)})
