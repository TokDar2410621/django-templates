# SETTINGS — stripe-connect-multivendor

## pip dependencies

```
stripe>=10
djangorestframework>=3.14
```

Optional:

```
django-unfold        # admin theme; otherwise stock ModelAdmin
```

## INSTALLED_APPS

```python
INSTALLED_APPS = [
    # ...
    "rest_framework",
    "stripe_connect_multivendor",
]
```

## URLs

```python
# config/urls.py
from django.urls import path, include

urlpatterns = [
    # ...
    path("api/payouts/", include("stripe_connect_multivendor.urls")),
]
```

Webhook URL is `/<your-prefix>/webhooks/stripe/` — must match what's
registered on the Stripe dashboard.

## Required settings

```python
# settings.py
from stripe_connect_multivendor.settings_helpers import _stripe_env

# Optional toggle — flips the next 3 vars in one shot
STRIPE_MODE = os.environ.get("STRIPE_MODE", "live").lower()  # "test" | "live"

# Stripe API key (resolves STRIPE_SECRET_KEY_TEST / _LIVE / fallback)
STRIPE_SECRET_KEY = _stripe_env("STRIPE_SECRET_KEY", STRIPE_MODE)

# Connect webhook endpoint signing secret
STRIPE_WEBHOOK_SECRET = _stripe_env("STRIPE_WEBHOOK_SECRET", STRIPE_MODE)

# Platform's Connect client ID (ca_xxx) — required for the OAuth flow
# Find at: https://dashboard.stripe.com/settings/connect
STRIPE_CONNECT_CLIENT_ID = _stripe_env("STRIPE_CONNECT_CLIENT_ID", STRIPE_MODE)
```

## Optional settings

```python
# Default currency for payouts (ISO 4217, uppercase). Override per-payout
# via the create_payout(currency=...) kwarg.
STRIPE_DEFAULT_CURRENCY = "CAD"

# Where to redirect after OAuth completes / fails. The view appends
# /connect/result?status=ok|cancelled to this base.
STRIPE_CONNECT_RETURN_URL = "https://yourapp.com"
# Falls back to FRONTEND_URL if STRIPE_CONNECT_RETURN_URL is empty.
```

## Env vars (read by `_stripe_env`)

When `STRIPE_MODE=test`:

| Setting                     | Resolves                              |
|----------------------------|---------------------------------------|
| `STRIPE_SECRET_KEY`         | `STRIPE_SECRET_KEY_TEST` → `STRIPE_SECRET_KEY` |
| `STRIPE_WEBHOOK_SECRET`     | `STRIPE_WEBHOOK_SECRET_TEST` → `STRIPE_WEBHOOK_SECRET` |
| `STRIPE_CONNECT_CLIENT_ID`  | `STRIPE_CONNECT_CLIENT_ID_TEST` → `STRIPE_CONNECT_CLIENT_ID` |

When `STRIPE_MODE=live` (the default), same shape with `_LIVE` suffix.

The fallback to the unsuffixed name preserves back-compat for projects
that haven't switched to the dual-credential layout yet.

## Stripe dashboard configuration

1. **Connect → Settings → Onboarding options** — set the **redirect
   URI** to `https://yourapp.com/api/payouts/connect/callback/` (and
   the test-mode equivalent).
2. **Developers → Webhooks → Add endpoint** — point at
   `https://yourapp.com/api/payouts/webhooks/stripe/`. Subscribe to:
   - `account.updated`
   - `transfer.created`
   - `transfer.reversed`

   Copy the signing secret into `STRIPE_WEBHOOK_SECRET` (or
   `_TEST` / `_LIVE` variant).

## Post-install verification

```bash
python manage.py check
python manage.py migrate
python manage.py test stripe_connect_multivendor
# or with pytest:
pytest apps/stripe_connect_multivendor/tests/

# Server running? Smoke-test the OAuth start (need a logged-in user
# with a Partner profile in the DB):
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"email":"partner@example.com","password":"…"}' | jq -r .token)

curl -s http://127.0.0.1:8000/api/payouts/connect/start/ \
  -H "Authorization: Bearer $TOKEN"
# → {"url": "https://connect.stripe.com/oauth/authorize?..."}
```
