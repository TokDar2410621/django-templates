"""Allauth ``SocialAccountAdapter`` — fills display_name + auto-links emails.

Wire it via ``settings.SOCIALACCOUNT_ADAPTER``::

    SOCIALACCOUNT_ADAPTER = "auth_jwt_oauth.adapters.DefaultSocialAdapter"

Behavior:

- **populate_user** : when a brand-new social login arrives, populate
  ``display_name`` from the OAuth payload (``name`` claim, then
  ``first_name + last_name``, then the email's local part). Falls back
  to ``"Utilisateur"`` so the field is never empty.
- **pre_social_login** : if an account with the same email already
  exists (created by a previous email/password signup), link the
  social account to it instead of crashing on the unique-email
  constraint.
- **save_user** : after Allauth saves the row, ensure the
  ``UserProfile`` exists and stamp ``terms_accepted_at``. Clicking
  "Continue with Google" while the consent disclosure is on screen
  counts as legal acceptance — Apple is identical.
"""
from __future__ import annotations

import logging

from allauth.account.utils import user_email
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib.auth import get_user_model
from django.utils.text import slugify

logger = logging.getLogger(__name__)

USERNAME_MAX_LEN = 30
DISPLAY_NAME_MAX_LEN = 80


class DefaultSocialAdapter(DefaultSocialAccountAdapter):
    """Generic Google + Apple adapter. Subclass for project-specific tweaks."""

    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)

        full_name = (data.get("name") or "").strip()
        if not full_name:
            first = (data.get("first_name") or "").strip()
            last = (data.get("last_name") or "").strip()
            full_name = f"{first} {last}".strip()
        if not full_name:
            email = user_email(user) or ""
            full_name = email.split("@")[0] if email else "Utilisateur"

        if hasattr(user, "display_name"):
            user.display_name = full_name[:DISPLAY_NAME_MAX_LEN]

        # Ensure ``username`` is set for user models that still require it.
        if hasattr(user, "username") and not getattr(user, "username", ""):
            email = user_email(user) or "user"
            base = slugify(email.split("@")[0])[: USERNAME_MAX_LEN - 4] or "user"
            user.username = self._unique_username(base)

        return user

    def pre_social_login(self, request, sociallogin):
        """Auto-link to an existing email/password account on the same email.

        Without this, a user who first signed up via email/password and
        later clicks "Continue with Google" would crash on the unique
        email constraint. Allauth handles the link cleanly once we
        connect the sociallogin to the existing user.
        """
        if sociallogin.is_existing:
            return
        email = user_email(sociallogin.user)
        if not email:
            return
        User = get_user_model()
        try:
            existing = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return
        except User.MultipleObjectsReturned:  # pragma: no cover — bad data
            logger.error(
                "smn_auth.social_login_dup_emails email=%s — using first match",
                email,
            )
            existing = User.objects.filter(email__iexact=email).first()
        sociallogin.connect(request, existing)

    def save_user(self, request, sociallogin, form=None):
        from django.utils import timezone

        user = super().save_user(request, sociallogin, form=form)
        # Stamp legal consent + ensure profile exists.
        try:
            from .models import UserProfile
            from django.conf import settings as dj_settings
            if getattr(dj_settings, "AUTH_JWT_USER_PROFILE_ENABLED", True):
                profile, _ = UserProfile.objects.get_or_create(user=user)
                changed_fields: list[str] = []
                if not profile.terms_accepted_at:
                    profile.terms_accepted_at = timezone.now()
                    changed_fields.append("terms_accepted_at")
                if hasattr(user, "display_name") and getattr(user, "display_name", ""):
                    if profile.display_name != user.display_name:
                        profile.display_name = user.display_name
                        changed_fields.append("display_name")
                if changed_fields:
                    profile.save(update_fields=changed_fields)
        except Exception:  # pragma: no cover — best-effort, never fail signin
            logger.exception(
                "smn_auth.social_login_profile_stamp_failed user_id=%s",
                getattr(user, "pk", None),
            )
        return user

    @staticmethod
    def _unique_username(base: str) -> str:
        User = get_user_model()
        candidate = base
        i = 1
        while User.objects.filter(username=candidate).exists():
            suffix = str(i)
            candidate = f"{base[:USERNAME_MAX_LEN - len(suffix)]}{suffix}"
            i += 1
        return candidate
