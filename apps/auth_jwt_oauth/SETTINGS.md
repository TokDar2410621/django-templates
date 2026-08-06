# SETTINGS — auth-jwt-oauth

## pip dependencies

```
djangorestframework>=3.14
djangorestframework-simplejwt[crypto]>=5.3
django-allauth>=0.61
dj-rest-auth>=6.0
```

Optional:

```
django-ratelimit       # enables 429 mapping in the custom exception handler
django-unfold          # admin theming; falls back to stock ModelAdmin
```

## INSTALLED_APPS

Allauth pulls in `django.contrib.sites`, so wire it in this order:

```python
INSTALLED_APPS = [
    # Django core
    "django.contrib.sites",

    # DRF + JWT
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",

    # Allauth + dj-rest-auth
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "allauth.socialaccount.providers.apple",
    "dj_rest_auth",

    # This template
    "auth_jwt_oauth",
]
SITE_ID = 1
```

## URLs

```python
# config/urls.py
from django.urls import path, include
from auth_jwt_oauth.urls import auth_urls, user_urls

urlpatterns = [
    # ...
    path("api/auth/", include((auth_urls, "smn_auth"), namespace="smn_auth")),
    path("api/user/", include((user_urls, "smn_user"), namespace="smn_user")),
]
```

## DRF + JWT settings

```python
from datetime import timedelta

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    # 429 instead of 403 for Ratelimited (no-op when django-ratelimit absent)
    "EXCEPTION_HANDLER": "auth_jwt_oauth.exceptions.custom_exception_handler",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(days=7),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "ROTATE_REFRESH_TOKENS": False,
    "BLACKLIST_AFTER_ROTATION": True,
}
```

## Allauth + dj-rest-auth settings

```python
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

ACCOUNT_AUTHENTICATION_METHOD = "email"
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_USERNAME_REQUIRED = False
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_USER_MODEL_USERNAME_FIELD = "username"

SOCIALACCOUNT_EMAIL_VERIFICATION = "none"
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_ADAPTER = "auth_jwt_oauth.adapters.DefaultSocialAdapter"

REST_AUTH = {
    "TOKEN_MODEL": None,
    "USE_JWT": True,
    "JWT_AUTH_HTTPONLY": False,
    "SESSION_LOGIN": False,
}
```

## Google OAuth provider

```python
from decouple import config

SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "APP": {
            "client_id": config("GOOGLE_CLIENT_ID", default=""),
            "secret":    config("GOOGLE_CLIENT_SECRET", default=""),
            "key":       "",
        },
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
    },
    # ... apple below
}
```

## Apple Sign-In provider

Apple's "client_secret" is NOT a static string — it's a short-lived JWT
signed with your `.p8` private key. Allauth signs it on every token
exchange. The template ships a `_load_apple_p8()` style helper inline
to let you provide the key two ways:

```python
from pathlib import Path
from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent.parent

def _load_apple_p8() -> str:
    """Load the Apple Sign-In .p8 private key.

    Either ``APPLE_PRIVATE_KEY_PATH`` (filesystem path, good for dev)
    or ``APPLE_PRIVATE_KEY`` (raw PEM with literal ``\\n`` separators,
    good for Railway-style env vars).
    """
    path = config("APPLE_PRIVATE_KEY_PATH", default="")
    if path:
        p = Path(path)
        if not p.is_absolute():
            p = BASE_DIR / p
        try:
            return p.read_text(encoding="utf-8")
        except OSError:
            return ""
    inline = config("APPLE_PRIVATE_KEY", default="")
    return inline.replace("\\n", "\n") if inline else ""


SOCIALACCOUNT_PROVIDERS = {
    # ... google above
    "apple": {
        # Allauth maps these OAuth2-App fields onto Apple's JWT triple
        # used to sign the dynamic client_secret on each token exchange:
        #   client_id        → JWT claim `sub` → Apple Services ID
        #   secret           → JWT header `kid` → Apple Key ID (10 chars)
        #   key              → JWT claim `iss` → Apple Team ID (10 chars)
        #   settings.certificate_key → ES256 signing key (.p8 content)
        "APP": {
            "client_id": config("APPLE_CLIENT_ID", default=""),
            "secret":    config("APPLE_KEY_ID", default=""),
            "key":       config("APPLE_TEAM_ID", default=""),
            "settings": {
                "certificate_key": _load_apple_p8(),
            },
        },
        "SCOPE": ["email", "name"],
    },
}
```

## Env vars

| Variable                  | Required? | Notes                                                     |
|---------------------------|-----------|-----------------------------------------------------------|
| `GOOGLE_CLIENT_ID`        | Google    | OAuth Client ID from Google Cloud Console                 |
| `GOOGLE_CLIENT_SECRET`    | Google    | Matching client secret                                    |
| `APPLE_CLIENT_ID`         | Apple     | Apple Services ID (e.g. `com.example.web`)                |
| `APPLE_KEY_ID`            | Apple     | 10-char Key ID from "Sign in with Apple" key             |
| `APPLE_TEAM_ID`           | Apple     | 10-char Team ID from your Apple Developer account         |
| `APPLE_PRIVATE_KEY_PATH`  | Apple-OR  | Path to the downloaded `.p8` file (preferred locally)     |
| `APPLE_PRIVATE_KEY`       | Apple-OR  | Raw `.p8` content with literal `\n` (preferred on Railway)|
| `FRONTEND_URL`            | reset     | Base URL used in the password-reset email link            |
| `DEFAULT_FROM_EMAIL`      | reset     | "From" address used by `send_mail`                         |

"Apple-OR" = provide either `APPLE_PRIVATE_KEY_PATH` or
`APPLE_PRIVATE_KEY`, not both.

## Configurable template settings (all optional)

```python
# Toggle the UserProfile 1-to-1 model. Set False if your user model
# already carries display_name / phone_e164 / is_banned / terms_accepted_at.
AUTH_JWT_USER_PROFILE_ENABLED = True

# Override the password-reset link base. Falls back to FRONTEND_URL.
AUTH_JWT_FRONTEND_URL = "https://app.example.com"

# Override the password-reset email subject.
AUTH_JWT_PASSWORD_RESET_SUBJECT = "Réinitialise ton mot de passe"
```

## Post-install verification

```bash
python manage.py check
python manage.py migrate
pytest apps/auth_jwt_oauth/tests/

# curl smoke (replace localhost with your dev URL):
curl -s -i -X POST http://127.0.0.1:8000/api/auth/signup/ \
  -H "Content-Type: application/json" \
  -d '{"email":"alice@example.com","password":"Sup3rSecret!2026",
       "display_name":"Alice","accept_terms":true}'

curl -s -i -X POST http://127.0.0.1:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"email":"alice@example.com","password":"Sup3rSecret!2026"}'

curl -s -i http://127.0.0.1:8000/api/auth/me/ \
  -H "Authorization: Bearer <access_token>"
```

## OAuth provider configuration cheatsheet

### Google Cloud Console

1. Create OAuth 2.0 Client ID (Web application).
2. Authorized JavaScript origins: your SPA's URL(s).
3. Authorized redirect URIs: `https://<your-backend>/accounts/google/login/callback/`
4. Copy Client ID + Client Secret into your env.

### Apple Developer

1. Create a **Services ID** (`com.example.web`) and enable Sign In with Apple.
2. Configure return URLs: `https://<your-backend>/accounts/apple/login/callback/`
3. Create a **Key** with "Sign In with Apple" enabled → download `.p8`.
4. Note the **Key ID** (10 chars) + your **Team ID** (10 chars, top right
   of the Apple Developer portal).
5. Wire `APPLE_CLIENT_ID` (Services ID) + `APPLE_KEY_ID` + `APPLE_TEAM_ID`
   + either `APPLE_PRIVATE_KEY_PATH` or `APPLE_PRIVATE_KEY`.
