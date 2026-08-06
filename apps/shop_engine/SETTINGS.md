# SETTINGS — shop-engine

## pip dependencies

```
djangorestframework>=3.14
```

Strongly recommended for any real deployment:

```
stripe>=8.0              # PaymentIntent + Refund + Webhook signature verify
celery>=5.3              # scheduled catalog sync + dispatch + cart sweep
redis>=5.0               # Celery broker
django-unfold            # if your admin uses Unfold; otherwise stock ModelAdmin
```

## INSTALLED_APPS

```python
INSTALLED_APPS = [
    # ...
    "rest_framework",
    "shop_engine",
]
```

## URLs

```python
# config/urls.py
from django.urls import path, include
from shop_engine.views import affiliate_landing_view

urlpatterns = [
    # ...
    path("api/shop/", include("shop_engine.urls")),
    # Referral landing — NOT under /api/ because it 302-redirects.
    path("r/<str:code>/", affiliate_landing_view),
]
```

## Configurable settings (all optional unless noted)

```python
# settings.py — all settings below have sensible defaults; override as needed.

# ---------------------------------------------------------------------------
# Currency + order numbering
# ---------------------------------------------------------------------------

# ISO 4217 — the default for Cart.currency / Product.currency / Order.currency.
# Mixed-currency shops are out of scope; one shop, one currency.
SHOP_DEFAULT_CURRENCY = "CAD"

# Prefix on the generated public order number (e.g. "ORD-2026-AB12CD34").
SHOP_ORDER_NUMBER_PREFIX = "ORD-"

# ---------------------------------------------------------------------------
# Providers (catalogue + fulfillment)
# ---------------------------------------------------------------------------

# Dotted paths to the implementing classes.
SHOP_CATALOG_PROVIDER = "shop_engine.providers.local.LocalCatalogProvider"
SHOP_FULFILLMENT_PROVIDER = "shop_engine.providers.fulfillment_local.LocalFulfillmentProvider"

# Stub provider credentials (only relevant when you swap the providers in).
ALIBABA_APP_KEY = ""
ALIBABA_APP_SECRET = ""
ALIBABA_ACCESS_TOKEN = ""

GELATO_API_KEY = ""
GELATO_BASE_URL = "https://order.gelatoapis.com"

# ---------------------------------------------------------------------------
# Stripe (REQUIRED for checkout; degraded if missing)
# ---------------------------------------------------------------------------

# Set both. Missing STRIPE_SECRET_KEY → checkout endpoints return 503.
STRIPE_SECRET_KEY = "sk_live_..."
STRIPE_WEBHOOK_SECRET = "whsec_..."

# For projects that want a test/live mode toggle: copy
# ../../snippets/stripe_mode_toggle.py into your settings/base.py — it
# flips between (STRIPE_SECRET_KEY_TEST, STRIPE_SECRET_KEY_LIVE) based
# on a STRIPE_MODE env var.

# ---------------------------------------------------------------------------
# Cart
# ---------------------------------------------------------------------------

# Anonymous carts past this age are wiped by ``tasks.expire_old_carts``.
SHOP_CART_EXPIRY_DAYS = 30

# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------

# False → guest checkout endpoints return 400. Force-login users.
SHOP_GUEST_CHECKOUT_ENABLED = True

# ---------------------------------------------------------------------------
# Tax + shipping (placeholders — override for your jurisdiction)
# ---------------------------------------------------------------------------

# Basis points on the taxable base. 1000 = 10%. Default 0 (no tax).
# Real projects override `cart_svc.calculate_totals` to plug a real
# tax engine (Quaderno / TaxJar / Avalara).
SHOP_TAX_RATE_BPS = 0

# Flat shipping fee, in cents. Override `calculate_totals` for any
# real shipping logic (origin + dest + weight + carrier).
SHOP_FLAT_SHIPPING_CENTS = 0

# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------

# True (default) → only customers who have a paid Order with the
# product can submit a review. False = open to anyone authenticated.
SHOP_REVIEW_REQUIRES_PURCHASE = True

# ---------------------------------------------------------------------------
# Affiliates
# ---------------------------------------------------------------------------

# Default commission for newly-created affiliates (in basis points).
# 1000 = 10%. Each affiliate can override on their row.
SHOP_AFFILIATE_DEFAULT_COMMISSION_BPS = 1000

# Cookie set by ``/r/<code>/`` to remember the referrer.
SHOP_AFFILIATE_COOKIE_NAME = "_shop_ref"
SHOP_AFFILIATE_COOKIE_TTL_DAYS = 30

# Where the referral landing 302-redirects to after stamping the cookie.
SHOP_AFFILIATE_LANDING_URL = "https://www.your-domain.com/"

# Magic-link token TTL for email-only affiliates. 0 = no expiry.
SHOP_MAGIC_LINK_TTL_HOURS = 24
```

## Celery beat snippet

```python
# settings.py — copy into CELERY_BEAT_SCHEDULE

CELERY_BEAT_SCHEDULE = {
    # Sync upstream catalogue (no-op for the local provider — safe to
    # leave running). 30 min is a sane default for marketplace
    # providers; tighten for stock-sensitive items.
    "shop-catalog-sync": {
        "task": "shop_engine.tasks.sync_catalog_from_provider",
        "schedule": 1800,
    },

    # Dispatch paid orders to the fulfillment provider. Tight cadence
    # so a customer's order moves to "fulfilling" within minutes of
    # payment confirmation.
    "shop-dispatch-paid-orders": {
        "task": "shop_engine.tasks.dispatch_paid_orders",
        "schedule": 300,
    },

    # Poll provider for orders in `fulfilling` state. Hourly is enough
    # for most POD providers; bump to 15min if your customers expect
    # near-real-time tracking updates.
    "shop-poll-provider-status": {
        "task": "shop_engine.tasks.poll_provider_order_status",
        "schedule": 3600,
    },

    # Sweep abandoned anonymous carts. Daily.
    "shop-expire-old-carts": {
        "task": "shop_engine.tasks.expire_old_carts",
        "schedule": 86400,
    },
}
```

If your project doesn't use Celery, you can call these as plain
functions from a management command — the `@shared_task` decorator
falls through.

## Env vars

| Variable                 | Required for                                       |
|--------------------------|----------------------------------------------------|
| `STRIPE_SECRET_KEY`      | Creating PaymentIntents, refunds, webhook signing  |
| `STRIPE_WEBHOOK_SECRET`  | Verifying incoming Stripe webhooks                 |
| `ALIBABA_APP_KEY`+`_SECRET`+`_ACCESS_TOKEN` | Only when wiring the Alibaba stub |
| `GELATO_API_KEY`         | Only when wiring the Gelato stub                   |

All are degraded-gracefully: missing them returns 503 from the
affected endpoint instead of crashing on boot.

## Post-install verification

```bash
python manage.py check
python manage.py migrate
pytest apps/shop_engine/tests/

# curl smoke (replace TOKEN with a real JWT/session cookie for protected endpoints):
curl -s http://127.0.0.1:8000/api/shop/products/
# expected: 200 {"results": [], "page": 1, ...}

curl -s -X POST -H "Content-Type: application/json" \
  -d '{"product_id": 1, "quantity": 2}' \
  http://127.0.0.1:8000/api/shop/cart/items/
# expected: 201 with the new cart payload
```

## Switching providers

To swap in a real Alibaba/Gelato/your-own provider:

1. Subclass the appropriate stub (or write fresh).
2. Replace the `NotImplementedError` bodies with HTTP calls.
3. Update settings:
   ```python
   SHOP_CATALOG_PROVIDER = "myproject.providers.MyCatalog"
   SHOP_FULFILLMENT_PROVIDER = "myproject.providers.MyFulfillment"
   ```
4. Run `python manage.py shell -c "from shop_engine.tasks import sync_catalog_from_provider; print(sync_catalog_from_provider())"` to seed.

## Wiring with other templates in this lib

- **`notifications_multichannel`** — handle order-confirmation /
  shipped / refunded emails by hooking `Order.post_save`. Also
  override `shop_engine.tasks.send_affiliate_payout_notification`
  to send a real payout email through your role-based sender.
- **`stripe_connect_multivendor`** — pair if you want
  Stripe-Connect-driven automatic transfers to affiliates. Adapt the
  Partner model there to wrap our Affiliate, OR keep them separate
  and use both (a Connect partner for big suppliers, an Affiliate
  for influencer codes).
- **`saas_billing_credits_quota`** — orthogonal. Subscriptions /
  credit packs live there; one-time product sales live here. Two
  Stripe customers can share one auth user.
- **`hashed_api_tokens`** — if you expose the admin API to a
  warehouse/3PL service, token-auth them through that template
  rather than a service account.
- **`legal_cms_pages`** — link /terms/, /privacy/, /shipping-policy/
  from the checkout footer.
- **Snippet `snippets/stripe_mode_toggle.py`** — copy into your
  settings module to support `STRIPE_MODE=test|live` env-var
  switching of secrets (matches what the SendMenow project does).
