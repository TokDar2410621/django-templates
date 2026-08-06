# auth-jwt-oauth

═════════════════════════════════════════════
Template : auth-jwt-oauth
Version  : 1.0.0
Mode     : EXTRACT-A
Source   : SMN/apps/users + FIN/apps/users
Stack    : Django 5+ / DRF / simplejwt / django-allauth / dj-rest-auth
Deps     : `djangorestframework`, `djangorestframework-simplejwt[crypto]`,
           `django-allauth`, `dj-rest-auth`, (optional) `django-ratelimit`,
           (optional) `django-unfold`
Used by  : (none yet)
═════════════════════════════════════════════

Email/password authentication with **JWT** access + refresh tokens, plus
**Google** and **Apple Sign-In** via Allauth + dj-rest-auth. Drop-in for
any Django project that wants a modern, SPA-friendly auth surface.

## Why this template

- **Email-as-login by default.** No more "did I sign up with my username
  or my email?" — ACCOUNT_AUTHENTICATION_METHOD is wired to `"email"`,
  the serializer normalizes case, and signup auto-generates a unique
  placeholder username when the user model still keeps one.
- **JWT response shape that matches what every SPA expects.** Every
  auth endpoint (signup / login / Google / Apple) returns
  `{ token, refresh, user }` so the frontend stores the same fields
  regardless of which sign-in route ran.
- **Apple Sign-In done right.** The `_load_apple_p8()` helper accepts
  either a filesystem path to the `.p8` (good for local dev) or the raw
  PEM with literal `\n` separators (good for Railway-style envs that
  only take single-line env vars).
- **Email-already-exists handled.** A user who signs up with
  `alice@example.com` via password, then later clicks "Continue with
  Google" with the same email, gets the Google account linked to the
  existing user instead of a unique-constraint crash.
- **Rate-limit aware.** Ships a `custom_exception_handler` that turns
  `django_ratelimit.exceptions.Ratelimited` into a clean **429**
  instead of DRF's default 403. The handler is import-guarded so the
  app still boots when `django-ratelimit` is absent.
- **Optional UserProfile.** Avoids forcing `AUTH_USER_MODEL` swap on
  adopters who already have one. The 1-to-1 profile row carries
  `display_name`, `phone_e164`, `is_banned` and `terms_accepted_at` —
  toggle it off with `AUTH_JWT_USER_PROFILE_ENABLED = False` if your
  user model already has these.

## API

| Method | Path                                       | Auth      | Purpose                                     |
|--------|--------------------------------------------|-----------|---------------------------------------------|
| POST   | `/api/auth/signup/`                        | none      | Email + password + display_name + accept_terms |
| POST   | `/api/auth/login/`                         | none      | Email + password → JWT pair                 |
| POST   | `/api/auth/logout/`                        | Bearer    | Blacklist a refresh token                   |
| GET    | `/api/auth/me/`                            | Bearer    | Current user shape                          |
| POST   | `/api/auth/check-email/`                   | none      | Email-first signup helper (`{exists: bool}`) |
| POST   | `/api/auth/token/refresh/`                 | none      | Refresh → new access token                  |
| POST   | `/api/auth/password-reset/request/`        | none      | Send reset email (always 200)               |
| POST   | `/api/auth/password-reset/confirm/`        | none      | `{uid, token, new_password}` → commit reset |
| POST   | `/api/auth/google/`                        | none      | Body: `{access_token | id_token}`           |
| POST   | `/api/auth/apple/`                         | none      | Body: `{id_token}`                          |
| DELETE | `/api/auth/account/`                       | Bearer    | Permanent deletion (typed confirmation)     |
| PATCH  | `/api/user/profile/`                       | Bearer    | Update `display_name` + `phone_e164`        |

Auth response shape:

```json
{
  "token": "<access_jwt>",
  "refresh": "<refresh_jwt>",
  "user": {
    "id": "1",
    "email": "alice@example.com",
    "display_name": "Alice",
    "phone_e164": "",
    "phone_verified": false,
    "is_staff": false,
    "date_joined": "2026-05-22T12:34:56Z"
  }
}
```

## Quickstart

```bash
pip install djangorestframework "djangorestframework-simplejwt[crypto]" \
            django-allauth dj-rest-auth
```

Add to `INSTALLED_APPS` — the order matters because Allauth depends on
`django.contrib.sites`:

```python
INSTALLED_APPS = [
    # ...
    "django.contrib.sites",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "allauth.socialaccount.providers.apple",
    "dj_rest_auth",
    "auth_jwt_oauth",
]
SITE_ID = 1
```

Wire URLs:

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

Migrate:

```bash
python manage.py migrate
```

Configure providers + JWT — see [SETTINGS.md](./SETTINGS.md) for the
complete env-var matrix (`GOOGLE_CLIENT_ID`, `APPLE_KEY_ID`, etc.).

## Testing

```bash
pytest apps/auth_jwt_oauth/tests/
```

The tests use the locmem email backend + DRF's `APIClient`. Run them
inside a host Django project that has the migration applied.

## Customization hooks

- `AUTH_JWT_USER_PROFILE_ENABLED` — flip to `False` when your user
  model already carries `display_name` / `phone_e164` / `is_banned` /
  `terms_accepted_at`. Disables the `UserProfile` 1-to-1.
- `AUTH_JWT_FRONTEND_URL` — base URL used to build the password-reset
  link in the email body. Falls back to `settings.FRONTEND_URL` if set.
- `AUTH_JWT_PASSWORD_RESET_SUBJECT` — override the email subject line.

## What this does NOT include

- **No User model swap.** This template attaches a `UserProfile` 1-to-1
  to whatever `AUTH_USER_MODEL` your project has. If you want a full
  email-first `AbstractUser` replacement, copy the `User` class from
  SMN/FIN — it's intentionally out of scope here so the template can
  drop into projects that already have a user model.
- **No guest / upgrade flow.** SMN/FIN have a "finder anonyme who
  later upgrades" UX with `is_guest` + `/api/auth/guest/` +
  `/api/auth/upgrade/`. That ships only on those products; leave it
  out unless you actually need it.
- **No social-auth providers beyond Google + Apple.** Adding
  Facebook/Twitter/etc. is one Allauth provider line away — see the
  Allauth docs.
- **No SMS verification.** `phone_verified` is just a boolean; wire
  Twilio (or equivalent) yourself if you need a verify-code flow.
- **No rate limits applied to views.** The custom exception handler
  knows how to render `Ratelimited` as 429, but the actual `@ratelimit`
  decorators belong in your project — opinions vary on per-IP vs
  per-user quotas.
