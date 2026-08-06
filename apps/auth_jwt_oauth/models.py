"""Optional ``UserProfile`` 1-to-1 extension for the project's auth user.

This template **does not** swap ``AUTH_USER_MODEL``. We attach a thin
``UserProfile`` row via OneToOne so projects keep whatever user model
(stock ``django.contrib.auth.User`` or their own custom one) they
already have.

The profile carries the handful of fields the serializers + admin in
this template actually need:

- ``display_name`` — human-friendly handle shown in the API ``/me/``
  response and used by the social adapter to capture the OAuth name.
- ``phone_e164`` — optional contact number (E.164 format).
- ``is_banned`` — admin moderation flag. ``LoginSerializer`` refuses to
  authenticate a banned user.
- ``terms_accepted_at`` — timestamp at which the user clicked "Accept"
  on the ToS/Privacy disclosure. Stamped automatically on signup +
  social login.

If your project already has these fields directly on the user model,
set ``AUTH_JWT_USER_PROFILE_ENABLED = False`` in settings — the views,
serializers and admin tolerate the missing profile gracefully via
``getattr(user, "<field>", default)``.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


def _profile_enabled() -> bool:
    """Whether to materialize the ``UserProfile`` model."""
    return bool(getattr(settings, "AUTH_JWT_USER_PROFILE_ENABLED", True))


class UserProfile(models.Model):
    """Per-user extension carrying display_name, phone, ban + ToS consent."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="smn_auth_profile",
        primary_key=True,
    )
    display_name = models.CharField(
        max_length=80,
        blank=True,
        default="",
        help_text="Nom d'affichage (montré dans l'app, défini à l'inscription).",
    )
    phone_e164 = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="Numéro de téléphone au format international (commence par +).",
    )
    phone_verified = models.BooleanField(default=False)

    is_banned = models.BooleanField(
        default=False,
        db_index=True,
        help_text=(
            "Utilisateur banni — la connexion par mot de passe est refusée."
        ),
    )

    terms_accepted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Horodatage de l'acceptation des CGU / politique de "
            "confidentialité. Null pour les comptes pré-existants."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "smn_auth_user_profile"
        verbose_name = "User profile"
        verbose_name_plural = "User profiles"

    def __str__(self) -> str:
        return self.display_name or str(self.user_id)


def get_or_create_profile(user) -> UserProfile:
    """Helper — fetch the profile row, lazily create it if missing.

    Cheaper than wrapping every call site in a try/except — but only
    safe to call once the ``auth_jwt_oauth`` migrations have run.
    """
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile
