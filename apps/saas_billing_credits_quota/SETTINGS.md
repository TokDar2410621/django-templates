# SETTINGS — saas-billing-credits-quota

## pip dependencies

```
stripe>=10
djangorestframework>=3.14
```

Optional:

```
django-unfold        # if your admin uses Unfold; otherwise falls back to stock ModelAdmin
```

## INSTALLED_APPS

```python
INSTALLED_APPS = [
    # ...
    "rest_framework",
    "saas_billing_credits_quota",
]
```

## URLs

```python
# config/urls.py
from django.urls import path, include

urlpatterns = [
    # ...
    path("api/billing/", include("saas_billing_credits_quota.urls")),
]
```

## Env vars

| Env var                          | Required           | Purpose                                                              |
|----------------------------------|--------------------|----------------------------------------------------------------------|
| `STRIPE_SECRET_KEY`              | yes (charging)     | `sk_live_...` or `sk_test_...`. Without it, checkout returns 503.   |
| `STRIPE_WEBHOOK_SECRET`          | yes (webhook)      | `whsec_...`. Without it, the webhook returns 503.                   |
| `FRONTEND_BASE_URL`              | recommended        | Used for Stripe success/cancel URLs. Default `http://localhost:3000`. |
| `STRIPE_PRICE_<PLAN_SLUG>`       | per-plan           | E.g. `STRIPE_PRICE_PRO=price_xxx`. See `SAAS_PLAN_STRIPE_PRICES` below. |
| `STRIPE_PRICE_CREDITS_<PACK>`    | per-credit-pack    | E.g. `STRIPE_PRICE_CREDITS_SMALL=price_yyy`. See `SAAS_CREDIT_PACKS` below. |

## Configurable settings (all have defaults — override as needed)

```python
# settings.py

# ---- Plans -----------------------------------------------------------------

SAAS_PLAN_CHOICES = [
    ("free",   "Essai (gratuit)"),
    ("solo",   "Solo"),
    ("pro",    "Pro"),
    ("agency", "Agence"),
]

SAAS_DEFAULT_PLAN = "free"

# {plan_slug: {resource_key: limit_or_None}}
# None = unlimited; missing key = limit 0 (not allowed).
SAAS_PLAN_LIMITS = {
    "free":   {"article_generation": 1,   "api_call": 100},
    "solo":   {"article_generation": 8,   "api_call": 1_000,  "export": 5},
    "pro":    {"article_generation": 60,  "api_call": 10_000, "export": 50},
    "agency": {"article_generation": 200, "api_call": None,   "export": None},
}

# Plan slug → env var name holding the Stripe Price ID.
# The webhook uses this to map subscription items back to your plan slug.
SAAS_PLAN_STRIPE_PRICES = {
    "solo":   "STRIPE_PRICE_SOLO",
    "pro":    "STRIPE_PRICE_PRO",
    "agency": "STRIPE_PRICE_AGENCY",
}

# ---- Credit packs (one-time top-up) ---------------------------------------

# Each pack has a Stripe Price ID stored in an env var. `credits` is the
# integer credited on successful payment.
SAAS_CREDIT_PACKS = {
    "small":  {"credits": 10,  "env": "STRIPE_PRICE_CREDITS_SMALL",  "label": "Petit boost"},
    "medium": {"credits": 50,  "env": "STRIPE_PRICE_CREDITS_MEDIUM", "label": "Boost moyen"},
    "large":  {"credits": 200, "env": "STRIPE_PRICE_CREDITS_LARGE",  "label": "Gros volume"},
}

# Display-only fallback price for the README / pricing page when env not yet wired.
SAAS_CREDIT_PRICE_USD = {"small": 25, "medium": 99, "large": 299}

# ---- Checkout URLs --------------------------------------------------------

# Frontend path that Stripe redirects back to. Combined with FRONTEND_BASE_URL.
SAAS_CHECKOUT_RETURN_PATH = "/billing"
```

## Stripe webhook setup

1. In the Stripe dashboard → Developers → Webhooks → "Add endpoint".
2. URL: `https://yourdomain/api/billing/stripe/webhook/`
3. Events to send:
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.payment_failed`
   - `invoice.payment_succeeded`
   - `checkout.session.completed`
4. Copy the "Signing secret" (`whsec_...`) into `STRIPE_WEBHOOK_SECRET`.

For local dev: `stripe listen --forward-to localhost:8000/api/billing/stripe/webhook/`
prints a `whsec_...` secret you can drop in your `.env` while the listener runs.

## Post-install verification

```bash
python manage.py check
python manage.py migrate

# Tests
pytest apps/saas_billing_credits_quota/tests/

# Smoke
TOKEN=...  # obtain JWT via your auth flow
curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8000/api/billing/me/ | jq

# Simulate a checkout request (returns a Stripe Checkout URL)
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"mode": "payment", "sku": "small"}' \
  http://127.0.0.1:8000/api/billing/checkout/ | jq
```
