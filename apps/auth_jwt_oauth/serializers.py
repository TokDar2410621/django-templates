"""Serializers — signup / login / password reset / user shape."""
from __future__ import annotations

from typing import Any

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .selectors import get_profile, is_banned
from .services import create_user

User = get_user_model()


def _strip_html(value: str) -> str:
    """Minimal scrub — strip leading/trailing whitespace + control chars.

    We deliberately don't pull bleach into this template's hard deps. If
    your project already has it installed, you can override this helper
    via ``AUTH_DISPLAY_NAME_SANITIZER`` (callable string in settings).
    """
    return "".join(c for c in (value or "") if c.isprintable() or c == " ").strip()


class UserSerializer(serializers.Serializer):
    """Public user shape — what /me/, /signup/, /login/ return.

    Reflects the user model + optional profile in a single object. We
    don't ``ModelSerializer`` here because the underlying ``User`` model
    is project-defined and may carry arbitrary extra fields we don't
    want to leak.
    """

    id = serializers.SerializerMethodField()
    email = serializers.EmailField(read_only=True)
    display_name = serializers.SerializerMethodField()
    phone_e164 = serializers.SerializerMethodField()
    phone_verified = serializers.SerializerMethodField()
    is_staff = serializers.BooleanField(read_only=True)
    date_joined = serializers.DateTimeField(read_only=True, required=False)

    def get_id(self, obj) -> str:
        return str(obj.pk)

    def _profile_value(self, obj, field: str, default: Any = "") -> Any:
        # Prefer the field directly on the user model; fall back to profile.
        if hasattr(obj, field):
            return getattr(obj, field) or default
        profile = get_profile(obj)
        return getattr(profile, field, default) if profile else default

    def get_display_name(self, obj) -> str:
        return self._profile_value(obj, "display_name", default="")

    def get_phone_e164(self, obj) -> str:
        return self._profile_value(obj, "phone_e164", default="")

    def get_phone_verified(self, obj) -> bool:
        return bool(self._profile_value(obj, "phone_verified", default=False))


class SignupSerializer(serializers.Serializer):
    """POST /api/auth/signup/ — email + password + display_name + ToS."""

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    display_name = serializers.CharField(max_length=80, min_length=1)
    accept_terms = serializers.BooleanField(write_only=True)

    def validate_accept_terms(self, value: bool) -> bool:
        if not value:
            raise serializers.ValidationError(
                "Tu dois accepter les conditions d'utilisation et la "
                "politique de confidentialité pour créer un compte."
            )
        return value

    def validate_email(self, value: str) -> str:
        normalized = value.strip().lower()
        if User.objects.filter(email__iexact=normalized).exists():
            raise serializers.ValidationError(
                "Un compte existe déjà avec ce courriel."
            )
        return normalized

    def validate_password(self, value: str) -> str:
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value

    def validate_display_name(self, value: str) -> str:
        cleaned = _strip_html(value)
        if not cleaned:
            raise serializers.ValidationError(
                "Le nom affiché ne peut pas être vide."
            )
        return cleaned[:80]

    def create(self, validated_data: dict):
        return create_user(
            email=validated_data["email"],
            password=validated_data["password"],
            display_name=validated_data["display_name"],
            accept_terms=True,
        )


class LoginSerializer(serializers.Serializer):
    """POST /api/auth/login/ — email + password."""

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    default_error_messages = {
        "invalid": "Identifiants invalides.",
        "banned": "Ce compte a été banni.",
    }

    def validate(self, attrs: dict) -> dict:
        email = attrs["email"].strip().lower()
        password = attrs["password"]
        # USERNAME_FIELD is typically email when this template is used —
        # but we pass it on both ``username`` and ``email`` kwargs so the
        # ModelBackend resolves it regardless.
        user = authenticate(
            request=self.context.get("request"),
            username=email,
            password=password,
        )
        if user is None:
            self.fail("invalid")
        if is_banned(user):
            self.fail("banned")
        attrs["user"] = user
        return attrs


class PasswordResetRequestSerializer(serializers.Serializer):
    """POST /api/auth/password-reset/request/ — { email }."""

    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    """POST /api/auth/password-reset/confirm/ — { uid, token, new_password }."""

    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True, min_length=8)

    def validate_new_password(self, value: str) -> str:
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value


class EmailCheckSerializer(serializers.Serializer):
    """POST /api/auth/check-email/ — { email }."""

    email = serializers.EmailField()


class UpdateProfileSerializer(serializers.Serializer):
    """PATCH /api/user/profile/ — display_name + phone_e164."""

    display_name = serializers.CharField(
        required=False, max_length=80, min_length=1,
    )
    phone_e164 = serializers.CharField(
        required=False, allow_blank=True, max_length=20,
    )

    def validate_display_name(self, value: str) -> str:
        cleaned = _strip_html(value)
        if not cleaned:
            raise serializers.ValidationError(
                "Le nom affiché ne peut pas être vide."
            )
        return cleaned[:80]

    def validate_phone_e164(self, value: str) -> str:
        v = (value or "").strip()
        if v and not v.startswith("+"):
            raise serializers.ValidationError(
                "Numéro de téléphone : format international requis "
                "(commence par +)."
            )
        return v
