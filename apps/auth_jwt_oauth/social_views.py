"""OAuth endpoints — Google + Apple Sign-In.

Subclass dj-rest-auth's ``SocialLoginView`` and override ``get_response``
so the wire shape matches our email/password login (``{token, refresh,
user}``). The frontend doesn't need to distinguish — it stores whichever
token it gets, the same way.

OAuth flow assumed:
  - **Google** : SPA uses Google Identity Services to fetch an
    ``access_token`` (or ``id_token``) and POSTs it to /api/auth/google/.
  - **Apple** : SPA uses "Sign in with Apple JS" to fetch an
    ``id_token`` (+ optional ``code``) and POSTs it to /api/auth/apple/.

The OAuth-app credentials live in ``SOCIALACCOUNT_PROVIDERS`` (see
SETTINGS.md). This view never sees the raw ``GOOGLE_CLIENT_SECRET`` /
Apple .p8 — Allauth uses them under the hood.
"""
from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

logger = logging.getLogger(__name__)


# Import-guard so the rest of the app boots cleanly when allauth /
# dj-rest-auth aren't installed (e.g. unit-testing in isolation).
try:
    from allauth.socialaccount.providers.apple.views import AppleOAuth2Adapter
    from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
    from allauth.socialaccount.providers.oauth2.client import (
        OAuth2Client,
        OAuth2Error,
    )
    from dj_rest_auth.registration.views import SocialLoginView

    _OAUTH_AVAILABLE = True
except ImportError:  # pragma: no cover — optional dependency stack
    AppleOAuth2Adapter = None  # type: ignore[assignment]
    GoogleOAuth2Adapter = None  # type: ignore[assignment]
    OAuth2Client = None  # type: ignore[assignment]
    OAuth2Error = Exception  # type: ignore[assignment]
    SocialLoginView = object  # type: ignore[misc,assignment]
    _OAUTH_AVAILABLE = False


from .serializers import UserSerializer  # noqa: E402

# Lazy-import to keep this module load-safe when simplejwt is absent.
def _tokens_for(user) -> tuple[str, str]:
    from rest_framework_simplejwt.tokens import RefreshToken
    refresh = RefreshToken.for_user(user)
    return str(refresh), str(refresh.access_token)


if _OAUTH_AVAILABLE:
    class _BaseSocialLoginView(SocialLoginView):  # type: ignore[misc]
        """Shared plumbing for Google + Apple — unified errors + response shape."""

        client_class = OAuth2Client
        permission_classes = (AllowAny,)
        authentication_classes = ()

        def post(self, request, *args, **kwargs):
            try:
                return super().post(request, *args, **kwargs)
            except OAuth2Error as exc:
                logger.warning("smn_auth.oauth_token_invalid err=%s", exc)
                return Response(
                    {
                        "detail": "Jeton OAuth invalide ou expiré.",
                        "error": str(exc),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            except TypeError as exc:
                # dj-rest-auth ↔ allauth 65.x signature mismatch surfaces
                # here on the unsupported authorization-code flow.
                logger.warning("smn_auth.oauth_signature_mismatch err=%s", exc)
                return Response(
                    {
                        "detail": (
                            "Le flux par code d'autorisation n'est pas "
                            "supporté. Utilise plutôt le SDK natif du "
                            "provider et envoie « access_token » ou "
                            "« id_token »."
                        ),
                        "error": str(exc),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        def get_response(self):
            user = self.user  # set by Allauth after the social login completed
            refresh, access = _tokens_for(user)
            return Response(
                {
                    "token": access,
                    "refresh": refresh,
                    "user": UserSerializer(
                        user, context={"request": self.request},
                    ).data,
                },
            )

    class GoogleLoginView(_BaseSocialLoginView):
        """POST /api/auth/google/ — body: ``{ access_token | id_token }``."""

        adapter_class = GoogleOAuth2Adapter
        callback_url = "postmessage"

    class AppleLoginView(_BaseSocialLoginView):
        """POST /api/auth/apple/ — body: ``{ id_token }``.

        Allauth verifies the JWT against Apple's JWKS and uses
        ``settings.SOCIALACCOUNT_PROVIDERS["apple"]`` for the signing key.
        """

        adapter_class = AppleOAuth2Adapter

else:
    # Fallback stubs so URL wiring doesn't crash when the OAuth stack
    # isn't installed. Each stub 503s with a clear error message.
    from rest_framework.views import APIView

    class _MissingOAuthView(APIView):
        permission_classes = (AllowAny,)
        authentication_classes = ()

        provider: str = "oauth"

        def post(self, request):
            return Response(
                {
                    "detail": (
                        "Le provider OAuth n'est pas installé sur ce "
                        f"backend ({self.provider}). Installe "
                        "`django-allauth` + `dj-rest-auth` puis configure "
                        "SOCIALACCOUNT_PROVIDERS."
                    ),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

    class GoogleLoginView(_MissingOAuthView):  # type: ignore[no-redef]
        provider = "google"

    class AppleLoginView(_MissingOAuthView):  # type: ignore[no-redef]
        provider = "apple"
