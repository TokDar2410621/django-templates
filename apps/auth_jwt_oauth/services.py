"""Auth services — user creation + password reset orchestration.

Layered architecture: views call into services; services do the
state changes and call selectors / external collaborators. Tests
mock at the service boundary, not at the view boundary.
"""
from __future__ import annotations

import logging
from typing import Optional

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from .models import UserProfile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Signup
# ---------------------------------------------------------------------------
def create_user(
    *,
    email: str,
    password: str,
    display_name: str = "",
    accept_terms: bool = True,
) -> object:
    """Create a verified-by-fiat email/password user + attach a profile.

    Validates the password against Django's validators. ``email`` is
    lower-cased and treated as the login identifier. The profile row is
    created with ``terms_accepted_at`` set to *now* when
    ``accept_terms`` is true.

    Caller is responsible for catching ``django.core.exceptions.ValidationError``
    when the password is rejected.
    """
    User = get_user_model()

    normalized_email = email.strip().lower()
    validate_password(password)

    # Whether the User model uses email as USERNAME_FIELD or has a
    # separate username field, we always feed both — ``create_user``
    # signature varies across project user models.
    kwargs: dict = {"email": normalized_email, "password": password}
    if getattr(User, "USERNAME_FIELD", "username") != "email":
        # Generate a placeholder username from the email local part.
        import uuid
        kwargs["username"] = f"u_{uuid.uuid4().hex[:12]}"

    user = User.objects.create_user(**kwargs)

    # Best-effort: write display_name onto the user model if it accepts
    # such a field. Otherwise it lives only on UserProfile.
    if display_name and hasattr(user, "display_name"):
        user.display_name = display_name[:80]
        try:
            user.save(update_fields=["display_name"])
        except (ValueError, TypeError):  # pragma: no cover — exotic user models
            user.save()

    if getattr(settings, "AUTH_JWT_USER_PROFILE_ENABLED", True):
        UserProfile.objects.update_or_create(
            user=user,
            defaults={
                "display_name": display_name[:80] if display_name else "",
                "terms_accepted_at": timezone.now() if accept_terms else None,
            },
        )

    logger.info(
        "smn_auth.user_created user_id=%s email=%s",
        getattr(user, "pk", None), normalized_email,
    )
    return user


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------
def request_password_reset(*, email: str, frontend_base_url: Optional[str] = None) -> bool:
    """Send a password-reset email with a tokenized link.

    Always returns ``True`` and never raises for an unknown email — that
    avoids leaking account-existence info to scrapers. The actual send
    is silently skipped when no account matches.

    ``frontend_base_url`` defaults to ``AUTH_JWT_FRONTEND_URL`` (or
    ``FRONTEND_URL``) from settings. The link format is::

        <base>/reset-password?uid=<uidb64>&token=<token>

    so the SPA can grab the two params and POST them to
    ``/api/auth/password-reset/confirm/``.
    """
    User = get_user_model()
    normalized = email.strip().lower()

    try:
        user = User.objects.get(email__iexact=normalized)
    except User.DoesNotExist:
        logger.info("smn_auth.password_reset_unknown_email email=%s", normalized)
        return True
    except User.MultipleObjectsReturned:  # pragma: no cover — bad data
        logger.error("smn_auth.password_reset_dup_emails email=%s", normalized)
        return True

    token = default_token_generator.make_token(user)
    uidb64 = urlsafe_base64_encode(force_bytes(user.pk))

    base = (
        frontend_base_url
        or getattr(settings, "AUTH_JWT_FRONTEND_URL", "")
        or getattr(settings, "FRONTEND_URL", "")
    )
    if not base:
        logger.error(
            "smn_auth.password_reset_no_frontend_url — set AUTH_JWT_FRONTEND_URL "
            "or FRONTEND_URL so the reset link points somewhere",
        )
        return True

    link = f"{base.rstrip('/')}/reset-password?uid={uidb64}&token={token}"

    subject = getattr(
        settings, "AUTH_JWT_PASSWORD_RESET_SUBJECT", "Réinitialise ton mot de passe",
    )
    from_email = getattr(
        settings, "DEFAULT_FROM_EMAIL", "noreply@example.com",
    )
    body = (
        f"Hello,\n\n"
        f"Tu as demandé une réinitialisation de mot de passe. Clique sur le "
        f"lien ci-dessous pour en choisir un nouveau :\n\n"
        f"{link}\n\n"
        f"Si tu n'es pas à l'origine de cette demande, ignore ce courriel.\n"
    )

    try:
        send_mail(subject, body, from_email, [user.email], fail_silently=False)
    except Exception:  # pragma: no cover — depends on the email backend
        logger.exception(
            "smn_auth.password_reset_email_send_failed user_id=%s",
            getattr(user, "pk", None),
        )
        return True

    logger.info(
        "smn_auth.password_reset_email_sent user_id=%s", getattr(user, "pk", None),
    )
    return True


def confirm_password_reset(*, uidb64: str, token: str, new_password: str) -> bool:
    """Validate the token + commit the new password.

    Returns ``True`` on success, ``False`` when the token or uid is
    invalid / expired. The password is validated through Django's
    validator chain — caller catches ``ValidationError`` for the
    "password too weak" case.
    """
    User = get_user_model()

    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        return False

    if not default_token_generator.check_token(user, token):
        return False

    validate_password(new_password, user=user)
    user.set_password(new_password)
    user.save(update_fields=["password"])
    logger.info(
        "smn_auth.password_reset_confirmed user_id=%s", getattr(user, "pk", None),
    )
    return True


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
def stamp_terms_accepted(user) -> None:
    """Mark the user's ToS as accepted *now*. Idempotent.

    Used by signup + the social adapter so the legal-consent timestamp
    is always present on freshly-created accounts.
    """
    if not getattr(settings, "AUTH_JWT_USER_PROFILE_ENABLED", True):
        return
    profile, _ = UserProfile.objects.get_or_create(user=user)
    if not profile.terms_accepted_at:
        profile.terms_accepted_at = timezone.now()
        profile.save(update_fields=["terms_accepted_at"])
