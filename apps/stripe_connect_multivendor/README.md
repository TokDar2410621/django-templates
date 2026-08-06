# stripe-connect-multivendor

═════════════════════════════════════════════
Template : stripe-connect-multivendor
Version  : 1.0.0
Mode     : EXTRACT-B (REWRITE — opinionated, decoupled from SMN's shop)
Source   : SMN/apps/shop (Partner / Affiliate / payout dispatcher)
Stack    : Django 5+ / DRF / Stripe SDK / (unfold optional)
Deps     : `stripe>=10`, `djangorestframework`
Used by  : (none yet)
═════════════════════════════════════════════

Stripe Connect (Standard mode) revenue-split payouts for a multivendor
platform. Each partner connects their existing Stripe account via OAuth;
this app records the share deals, fires `Transfer.create` when an order
ships, and keeps an append-only ledger of every transfer.

## Why this template

- **Decoupled from your order schema.** Calls into the app are keyed
  by string `external_order_id` / `external_order_item_id` — the
  template never imports your `Order` / `OrderItem` / `Product`
  models. You own the schema, this app owns the financial trail.
- **Stripe Connect Standard, done right.** OAuth state is signed and
  expires after 10 minutes; the callback exchanges `code` for an
  `acct_xxx` and requests the `transfers` capability without crashing
  on Standard accounts (whose `Account.modify` is forbidden — the
  service falls back to `Account.retrieve`).
- **Basis-point pricing.** Shares are stored as integers (`7000 bps`
  = `70.00%`) — no Decimal-vs-float debate, no rounding drift, plus
  it mirrors how Stripe encodes `application_fee_amount`.
- **Per-SKU overrides.** A partner can have a different deal for a
  specific product without polluting their default. Resolution order
  is line override → SKU override → partner default.
- **Append-only ledger.** Every `Transfer.create` is recorded as a
  `Payout` row with the gross/share snapshot. We never update those
  columns after the fact — only `status`, `stripe_transfer_id`,
  `error`, and `paid_at` move forward.
- **Idempotent.** `unique_together(external_order_item_id, partner)`
  guarantees one row per (item, partner). `idempotency_key="scm_payout_<pk>"`
  lets Stripe deduplicate retries server-side.
- **Mode toggle.** A single `STRIPE_MODE=test|live` env var flips the
  whole secret/webhook/connect-client-id triple. Helper lives in
  `settings_helpers._stripe_env`.
- **Optional Affiliate.** A second model for referral-code commissions
  ships in the same app but is ignorable if you don't need it.

## Why REWRITE (not extract)

SMN's `apps/shop` is huge (~1700-line `models.py`, multi-partner
through-model, printer routing, modeltranslation, CAD-only,
checkout/cart/order pipeline). Extracting just the Connect bits
inline would have dragged half the shop along. The patterns are
preserved (share_bps + flat fee, per-SKU override, `_stripe_env`
toggle, append-only ledger, account.updated → verified flag, OAuth
state signing) but the schema is rebuilt from scratch with sane
defaults and the right indirection.

## API

| Method | Path                          | Auth          | Purpose |
|--------|-------------------------------|---------------|---------|
| GET    | `/connect/start/`             | Authenticated | Returns Stripe OAuth URL for the current user's partner profile |
| GET    | `/connect/callback/`          | None          | Stripe redirects here with `code`+`state` → links partner |
| GET    | `/payouts/`                   | Authenticated | Own payout history (newest first) |
| POST   | `/webhooks/stripe/`           | Stripe sig    | `account.updated` / `transfer.created` / `transfer.reversed` |

(Mount under any prefix in your `config/urls.py`; webhook URL must
match what's registered on the Stripe dashboard.)

## Quickstart

```bash
pip install stripe djangorestframework
```

Add to `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    # ...
    "rest_framework",
    "stripe_connect_multivendor",
]
```

Wire URLs:

```python
# config/urls.py
urlpatterns = [
    # ...
    path("api/payouts/", include("stripe_connect_multivendor.urls")),
]
```

Configure Stripe (see `SETTINGS.md` for the full list):

```python
# settings.py
from stripe_connect_multivendor.settings_helpers import _stripe_env

STRIPE_MODE = os.environ.get("STRIPE_MODE", "live").lower()
STRIPE_SECRET_KEY = _stripe_env("STRIPE_SECRET_KEY", STRIPE_MODE)
STRIPE_WEBHOOK_SECRET = _stripe_env("STRIPE_WEBHOOK_SECRET", STRIPE_MODE)
STRIPE_CONNECT_CLIENT_ID = _stripe_env("STRIPE_CONNECT_CLIENT_ID", STRIPE_MODE)
STRIPE_DEFAULT_CURRENCY = "CAD"
STRIPE_CONNECT_RETURN_URL = "https://yourapp.com"  # frontend root
```

Migrate:

```bash
python manage.py migrate
```

## Integration — calling pattern

Your project keeps owning its Order / OrderItem models. When an order
transitions to PAID (Stripe webhook, success callback, whatever), call
`bulk_payout_for_order` with the line items:

```python
from stripe_connect_multivendor.services import bulk_payout_for_order

def on_order_paid(order):
    line_items = []
    for item in order.items.all():
        if not item.product.partner_id:
            continue
        line_items.append({
            "external_order_item_id": str(item.pk),
            "gross_cents": item.line_total_cents,
            "partner_id": item.product.partner_id,
            "external_product_id": item.product.slug,  # for SKU overrides
            # optional: "share_bps_override": 9000 for a promo line
        })
    bulk_payout_for_order(
        external_order_id=str(order.pk),
        line_items=line_items,
    )
```

For one-off payouts (e.g. a bonus you owe a partner) call
`create_payout` directly with synthetic IDs.

## Stripe webhook setup

In the Stripe dashboard, register a Connect webhook endpoint pointing
at `/<your-prefix>/webhooks/stripe/` and subscribe to:

- `account.updated`
- `transfer.created` (optional — only matters if you create transfers
  out-of-band)
- `transfer.reversed`

Copy the signing secret into `STRIPE_WEBHOOK_SECRET` (or
`STRIPE_WEBHOOK_SECRET_TEST` / `_LIVE` if you use the mode toggle).

## Testing

```bash
pytest apps/stripe_connect_multivendor/tests/
```

Tests stub the Stripe SDK module (see `tests/conftest.py`) so they
run without the `stripe` package installed and without hitting the
network.

## Customization hooks

- `STRIPE_MODE` — `"test"` or `"live"`; flips the credential triple
- `STRIPE_DEFAULT_CURRENCY` — default `"CAD"`; per-payout override
  via the `currency=` kwarg
- `STRIPE_CONNECT_RETURN_URL` — where to redirect after OAuth
  completes (frontend landing page)

## What this does NOT include

- **Express onboarding.** Standard-only — partners must have (or
  create) their own Stripe account. Add an Express path in your
  project if you want to onboard partners who don't have one (the
  patterns are in SMN's `stripe_client.create_connect_account`).
- **Order / cart / catalog models.** This app stays decoupled — you
  own the order schema and call `bulk_payout_for_order` from your
  own paid-handler.
- **Modeltranslation.** Field names are English-only; localise via
  `verbose_name` overrides in your own admin if you need to.
- **Payout-to-bank scheduling.** Stripe's own payout schedule handles
  Connect account payouts; this app just creates Transfers. The
  cadence (daily/weekly) is set in the partner's own Stripe dashboard.
