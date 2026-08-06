"""Auth views — signup, login, JWT lifecycle, password reset, me, profile."""
from __future__ import annotations

import logging
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from .selectors import email_exists, get_profile
from .serializers import (
    EmailCheckSerializer,
    LoginSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    SignupSerializer,
    UpdateProfileSerializer,
    UserSerializer,
)
from .services import (
    confirm_password_reset,
    request_password_reset,
)

User = get_user_model()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _tokens_for(user) -> tuple[str, str]:
    """Mint a refresh + access pair."""
    refresh = RefreshToken.for_user(user)
    return str(refresh), str(refresh.access_token)


def _auth_response(user, request, http_status: int = status.HTTP_200_OK) -> Response:
    """Standard ``{token, refresh, user}`` shape consumed by the SPA."""
    refresh, access = _tokens_for(user)
    return Response(
        {
            "token": access,
            "refresh": refresh,
            "user": UserSerializer(user, context={"request": request}).data,
        },
        status=http_status,
    )


# ---------------------------------------------------------------------------
# Signup / Login / Logout
# ---------------------------------------------------------------------------
class SignupView(APIView):
    """POST /api/auth/signup/ — email + password + display_name + accept_terms."""

    permission_classes = (AllowAny,)
    authentication_classes = ()

    def post(self, request: Request) -> Response:
        serializer = SignupSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return _auth_response(user, request, http_status=status.HTTP_201_CREATED)


class LoginView(APIView):
    """POST /api/auth/login/ — { email, password } → { token, refresh, user }."""

    permission_classes = (AllowAny,)
    authentication_classes = ()

    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        return _auth_response(serializer.validated_data["user"], request)


class LogoutView(APIView):
    """POST /api/auth/logout/ — { refresh } → blacklist the refresh token."""

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        refresh_value = request.data.get("refresh") if request.data else None
        if refresh_value:
            try:
                RefreshToken(refresh_value).blacklist()
            except TokenError:
                return Response(
                    {"detail": "Jeton de rafraîchissement invalide ou déjà expiré."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Email-first auth UX
# ---------------------------------------------------------------------------
class EmailCheckView(APIView):
    """POST /api/auth/check-email/ — { email } → { exists: bool }.

    Powers the email-first signup flow: the SPA asks the user for their
    email, hits this endpoint, then shows either the login form or the
    signup form. Rate-limit at the project level to keep account
    enumeration impractical.
    """

    permission_classes = (AllowAny,)
    authentication_classes = ()

    def post(self, request: Request) -> Response:
        ser = EmailCheckSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        return Response({"exists": email_exists(ser.validated_data["email"])})


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------
class PasswordResetRequestView(APIView):
    """POST /api/auth/password-reset/request/ — { email }.

    Always returns 200 so we don't leak account existence.
    """

    permission_classes = (AllowAny,)
    authentication_classes = ()

    def post(self, request: Request) -> Response:
        ser = PasswordResetRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        request_password_reset(email=ser.validated_data["email"])
        return Response(
            {
                "detail": (
                    "Si un compte existe pour cette adresse, un courriel "
                    "de réinitialisation a été envoyé."
                ),
            },
        )


class PasswordResetConfirmView(APIView):
    """POST /api/auth/password-reset/confirm/ — { uid, token, new_password }."""

    permission_classes = (AllowAny,)
    authentication_classes = ()

    def post(self, request: Request) -> Response:
        ser = PasswordResetConfirmSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            ok = confirm_password_reset(
                uidb64=ser.validated_data["uid"],
                token=ser.validated_data["token"],
                new_password=ser.validated_data["new_password"],
            )
        except DjangoValidationError as exc:
            return Response(
                {"new_password": list(exc.messages)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not ok:
            return Response(
                {"detail": "Lien de réinitialisation invalide ou expiré."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"detail": "Mot de passe mis à jour."})


# ---------------------------------------------------------------------------
# Profile (/me/, PATCH profile)
# ---------------------------------------------------------------------------
class MeView(APIView):
    """GET /api/auth/me/ — current user shape."""

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        return Response(
            UserSerializer(request.user, context={"request": request}).data,
        )


class UpdateProfileView(APIView):
    """PATCH /api/user/profile/ — display_name + phone_e164."""

    permission_classes = (IsAuthenticated,)
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def patch(self, request: Request) -> Response:
        ser = UpdateProfileSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)

        user = request.user
        data: dict[str, Any] = ser.validated_data

        # Persist on the user model if it accepts the fields…
        user_changed: list[str] = []
        for field in ("display_name", "phone_e164"):
            if field in data and hasattr(user, field):
                setattr(user, field, data[field])
                user_changed.append(field)
        if user_changed:
            user.save(update_fields=user_changed)

        # …and on the UserProfile (idempotent — covers either layout).
        profile = get_profile(user)
        if profile is not None:
            profile_changed: list[str] = []
            if "display_name" in data:
                profile.display_name = data["display_name"]
                profile_changed.append("display_name")
            if "phone_e164" in data:
                new_phone = data["phone_e164"]
                if new_phone != profile.phone_e164:
                    profile.phone_verified = False
                    profile_changed.append("phone_verified")
                profile.phone_e164 = new_phone
                profile_changed.append("phone_e164")
            if profile_changed:
                profile.updated_at = timezone.now()
                profile.save(update_fields=profile_changed + ["updated_at"])

        return Response(
            UserSerializer(user, context={"request": request}).data,
        )


# ---------------------------------------------------------------------------
# Delete account
# ---------------------------------------------------------------------------
class DeleteAccountView(APIView):
    """DELETE /api/auth/account/ — permanently delete the caller's account.

    Caller must type a confirmation word in the request body to avoid
    one-click deletions from a stale tab. Cascades to all FK rows.
    """

    CONFIRMATION_WORD = "SUPPRIMER"
    permission_classes = (IsAuthenticated,)

    def delete(self, request: Request) -> Response:
        payload = request.data or {}
        confirmation = (payload.get("confirmation", "") or "").strip().upper()
        if confirmation != self.CONFIRMATION_WORD:
            return Response(
                {
                    "detail": (
                        f'Tape "{self.CONFIRMATION_WORD}" pour confirmer la '
                        f"suppression."
                    ),
                    "expected": self.CONFIRMATION_WORD,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        request.user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
