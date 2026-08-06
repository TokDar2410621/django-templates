# shop-engine

═════════════════════════════════════════════
Template : shop-engine
Version  : 1.0.0
Mode     : CREATE (inspired by SendMenow's apps/shop)
Stack    : Django 5+ / DRF / Stripe / Celery (optional) / (unfold optional)
Deps     : `djangorestframework`, `stripe` (optional at boot)
Used by  : (none yet — first integration)
═════════════════════════════════════════════

A single-tenant Django storefront with affiliates and a provider
abstraction. Ships everything a real e-commerce site needs: catalogue
+ variants + reviews, cart (anon-or-authenticated), Stripe checkout
(guest-or-user), order state machine, coupon system, hybrid affiliate
program (user-FK *or* email-only with magic-link login), and a small
provider layer so the same engine works for products you stock
yourself or resell from upstream catalogues (Alibaba, Gelato, ...).

## Why this template

- **Single-tenant by design.** One deployment = one shop. There's no
  `tenant` FK on models — adding multi-tenancy means forking the
  template (the design calls around scope of slugs / codes / coupon
  codes all branch on it). For multi-tenant SaaS, wrap this engine in
  an `organisations` proxy that owns one deployment per row.
- **Integer cents everywhere.** All amounts are `IntegerField` in the
  smallest currency unit. Decimals introduce rounding bugs the moment
  you start splitting commissions / discounts proportionally across
  cart lines.
- **Hybrid affiliate auth.** The same `Affiliate` row supports both
  user-based affiliates (FK to your `User` — logs in normally) AND
  email-only affiliates (no user, logs in via emailed magic link). Use
  the former for customers-who-also-promote and the latter for
  external partners who shouldn't need a regular account.
- **Provider abstraction.** Two Protocols (`CatalogProvider`,
  `FulfillmentProvider`) + a default local implementation + stub
  examples for Alibaba (catalogue) and Gelato (POD fulfillment). The
  stubs raise `NotImplementedError` with the expected wire shape in
  the docstring so you have a template to fill in when wiring a real
  integration.
- **Snapshot-everything orders.** Once placed, orders carry their own
  copies of product titles, variant labels, applied coupon codes, and
  affiliate codes — so deleting the underlying rows doesn't break the
  receipt or the audit trail.
- **Idempotent webhooks.** Stripe webhooks are matched by
  `payment_intent_id`; replaying the same event is a no-op. Coupon and
  affiliate-conversion rows are unique on `(target, order)` so retries
  can't double-count.
- **Degraded mode.** Missing `STRIPE_SECRET_KEY` doesn't crash boot —
  checkout endpoints return `503 STRIPE_NOT_CONFIGURED`. Same for the
  provider stubs missing their API keys. Tests of unrelated services
  (cart math, admin) don't need any creds.

## Models (18)

**Catalogue**

- `Category` — self-FK tree, slug-unique
- `Tag` — flat, slug-unique
- `Product` — `provider` + `external_id` keyed for upstream sync, JSON `images`
- `ProductVariant` — sku-unique, `attributes` JSON, optional `track_inventory`
- `ProductReview` — 1–5 stars, `is_verified_purchase` auto-flagged
- `Wishlist` / `WishlistItem`

**Cart + orders**

- `Cart` — `user` XOR `session_key`, snapshotted `currency` + `affiliate_code`
- `CartItem` — unique on `(cart, product, variant)`, price snapshotted
- `Order` — state machine (draft → awaiting_payment → paid → fulfilling → shipped → delivered, branches to refunded / cancelled / failed)
- `OrderItem` — fully snapshotted (title, label, sku, prices, qty)

**Coupons**

- `Coupon` — `percent` / `fixed` / `free_shipping` with min-order + product scope + max-uses caps
- `CouponUsage` — unique on `(coupon, order)`, increments `times_used` atomically

**Affiliates**

- `Affiliate` — `user` FK nullable; if null, email + magic_link_token govern auth
- `AffiliateClick` — per-landing audit, cookie_id for later attribution
- `AffiliateConversion` — unique on `(affiliate, order)`, snapshots bps + flat
- `AffiliatePayout` — batched per-period, paid via the operator's choice of rail

**Audit**

- `ProviderSyncLog` — append-only log of every provider interaction (sync, dispatch, status fetch)

## API

### Catalogue (public)

| Method | Path                                       | Purpose                                  |
|--------|--------------------------------------------|------------------------------------------|
| GET    | `/api/shop/products/`                      | Paginated list + filters                 |
| GET    | `/api/shop/products/<slug>/`               | Full product payload                     |
| GET    | `/api/shop/products/<slug>/reviews/`       | Published reviews                        |
| GET    | `/api/shop/categories/`                    | Nested category tree                     |

### Cart (anon or auth)

| Method | Path                                          | Purpose                              |
|--------|-----------------------------------------------|--------------------------------------|
| GET    | `/api/shop/cart/`                             | Current cart (auto-created)          |
| POST   | `/api/shop/cart/items/`                       | Add line — body: `{product_id, variant_id?, quantity}` |
| PATCH  | `/api/shop/cart/items/<id>/`                  | Update qty (0 = remove)              |
| DELETE | `/api/shop/cart/items/<id>/`                  | Remove                               |
| POST   | `/api/shop/cart/apply-coupon/`                | `{code}`                             |
| POST   | `/api/shop/cart/remove-coupon/`               |                                      |

### Checkout (auth or guest)

| Method | Path                          | Purpose                                                |
|--------|-------------------------------|--------------------------------------------------------|
| POST   | `/api/shop/checkout/`         | Returns `{order_number, stripe_client_secret, order}`  |

### Orders (auth, owner-only)

| Method | Path                                       | Purpose                       |
|--------|--------------------------------------------|-------------------------------|
| GET    | `/api/shop/orders/`                        | Own orders                    |
| GET    | `/api/shop/orders/<order_number>/`         | Single order                  |
| POST   | `/api/shop/orders/lookup/`                 | Guest lookup `{email, order_number}` |

### Reviews + wishlist (auth)

| Method | Path                                  | Purpose                       |
|--------|---------------------------------------|-------------------------------|
| POST   | `/api/shop/reviews/`                  | Submit review                 |
| GET/POST | `/api/shop/wishlist/`               | View / add                    |
| DELETE | `/api/shop/wishlist/items/<id>/`      | Remove                        |

### Webhooks

| Method | Path                                   | Provider              |
|--------|----------------------------------------|-----------------------|
| POST   | `/api/shop/webhooks/stripe/`           | Stripe (HMAC verified)|

### Affiliate landing (public — sets cookie)

| Method | Path                | Purpose                                                 |
|--------|---------------------|---------------------------------------------------------|
| GET    | `/r/<code>/`        | Records `AffiliateClick`, sets `_shop_ref` cookie, redirects to `SHOP_AFFILIATE_LANDING_URL` |

### Affiliate dashboard (magic-link OR auth)

| Method | Path                                              | Purpose                       |
|--------|---------------------------------------------------|-------------------------------|
| POST   | `/api/shop/affiliates/login/`                     | `{email}` → magic-link sent   |
| GET    | `/api/shop/affiliates/me/?token=<magic>`          | Dashboard summary             |
| GET    | `/api/shop/affiliates/me/conversions/`            | List of conversions           |
| GET    | `/api/shop/affiliates/me/payouts/`                | List of payouts               |

### Admin (staff only)

`/api/shop/admin/products/` (full CRUD), `/api/shop/admin/categories/`,
`/api/shop/admin/orders/` (read + actions `refund`, `mark_fulfilled`,
`mark_shipped`, `cancel`), `/api/shop/admin/coupons/`,
`/api/shop/admin/affiliates/`, `/api/shop/admin/affiliate-payouts/`
(action `generate_for_period`).

## Quickstart

```bash
pip install djangorestframework
# When you're ready to take payments:
pip install stripe
```

Add to `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    # ...
    "rest_framework",
    "shop_engine",
]
```

Wire URLs:

```python
# config/urls.py
from django.urls import path, include
from shop_engine.views import affiliate_landing_view

urlpatterns = [
    # ...
    path("api/shop/", include("shop_engine.urls")),
    path("r/<str:code>/", affiliate_landing_view),  # referral landing
]
```

Migrate and create your first product in the admin:

```bash
python manage.py migrate
python manage.py createsuperuser
# Visit /admin/shop_engine/ → Categories → Tags → Products → ProductVariants
```

See [SETTINGS.md](./SETTINGS.md) for the full configuration matrix +
recommended Celery beat schedule.

## Provider integration guide

The default `LocalCatalogProvider` + `LocalFulfillmentProvider` mean
you manage everything in the admin and fulfill manually. To wire an
upstream catalogue or POD provider:

1. **Pick a provider stub to copy.** `providers/alibaba_stub.py` for a
   catalogue source, `providers/gelato_stub.py` for fulfillment. Both
   document the expected request/response shapes in docstrings.
2. **Copy + fill in.** Put your real client in
   `myproject/providers/<vendor>.py`. Each method's docstring already
   describes the wire shape — your job is to replace the
   `NotImplementedError` body with the HTTP call.
3. **Point settings at it.**
   ```python
   SHOP_CATALOG_PROVIDER = "myproject.providers.MyVendor"
   SHOP_FULFILLMENT_PROVIDER = "myproject.providers.MyVendorFulfillment"
   ```
4. **Wire the Celery beat schedule** so the upstream catalogue stays
   synced and paid orders dispatch automatically. See SETTINGS.md.

For projects that mix two providers (e.g. Local-managed t-shirts + a
Gelato POD line), implement a dispatcher that picks based on
`product.provider` and use that as your `SHOP_FULFILLMENT_PROVIDER`.

## Checkout pipeline in detail

```
FE adds items to /api/shop/cart/items/
     |
     v
POST /api/shop/checkout/
     |  cart_svc.calculate_totals()
     v
services.checkout.create_checkout()
     |  - Snapshots every cart line into OrderItem
     |  - Creates Stripe PaymentIntent (amount = total_cents)
     |  - Records CouponUsage + increments Coupon.times_used
     |  - Returns (order, stripe_client_secret)
     v
FE confirms PaymentIntent via Stripe.js (browser)
     |
     v
Stripe webhook → POST /api/shop/webhooks/stripe/
     |  services.checkout.process_stripe_webhook()
     v
- payment_intent.succeeded  → confirm_payment(order) → status=paid + cart cleared
                                                     → affiliate conversion recorded (if any)
- payment_intent.payment_failed → mark_failed(order)
- charge.refunded           → orders._mark_refunded_from_webhook(order)
```

A crash mid-flow leaves the Order in `awaiting_payment` with a valid
PaymentIntent. A retry on the FE picks up the same Order (idempotent
check in `create_checkout`).

## Affiliate attribution in detail

1. Visitor clicks `https://yourshop.com/r/<code>/`.
2. `affiliate_landing_view` records an `AffiliateClick` row and sets
   the `_shop_ref` cookie (value = the code), then 302-redirects to
   `SHOP_AFFILIATE_LANDING_URL`.
3. FE (or a tiny snippet on the storefront) reads the cookie and POSTs
   the code onto `Cart.affiliate_code` (`PATCH /api/shop/cart/` would
   be a project-specific extension — the cart serializer accepts it).
4. At checkout, `Cart.affiliate_code` is snapshotted onto
   `Order.affiliate_code`.
5. On `payment_intent.succeeded`, `confirm_payment` calls
   `affiliates.attribute_conversion(order, code)` which creates an
   `AffiliateConversion` row with snapshotted `commission_bps` + flat.

For the operator's payout workflow:

1. Once a month, hit `POST /api/shop/admin/affiliate-payouts/generate_for_period/`
   with `{period_start, period_end}`.
2. Service aggregates every `approved` conversion in the period per
   affiliate into one `AffiliatePayout` row.
3. Operator processes the actual money movement (PayPal, bank
   transfer, etc. — out of scope for this template) and calls
   `POST /api/shop/admin/affiliate-payouts/<id>/mark_paid/` with the
   external reference.
4. Linked conversions transition to `paid`; `Affiliate.total_paid_cents`
   increments.

## Integration with notifications-multichannel

This template doesn't ship an email backend. If you also use
`notifications_multichannel`:

```python
# myproject/shop_emails.py
from django.dispatch import receiver
from django.db.models.signals import post_save
from notifications_multichannel.services import send_email
from shop_engine.models import Order

@receiver(post_save, sender=Order)
def send_order_emails(sender, instance: Order, created, **kwargs):
    if instance._previous_status == instance.status:
        return
    if instance.status == Order.STATUS_PAID:
        send_email(
            to=instance.email, role="orders",
            subject=f"Order {instance.order_number} confirmed",
            html=render_to_string("emails/order_confirmed.html", {"order": instance}),
        )
```

Also override `shop_engine.tasks.send_affiliate_payout_notification`
in your project to fire on payout creation.

## What this does NOT include

- **An order-confirmation email template.** Bring your own — the
  template doesn't render HTML emails. Hook into `Order.post_save`
  (see signal example above) and use your project's email backend.
- **Tax calculation.** `SHOP_TAX_RATE_BPS` does a flat-rate tax on the
  taxable base, which is wrong for any real jurisdiction. Plug in
  Quaderno / Avalara / TaxJar via a small adapter that overrides
  `cart_svc.calculate_totals` (subclass it in a project file).
- **Shipping rate computation.** Same story —
  `SHOP_FLAT_SHIPPING_CENTS` is a single number. Real shipping
  needs origin + destination + weight + carrier rules. Override
  `calculate_totals` to plug in EasyPost / ShipEngine / direct
  carrier APIs.
- **Stripe Connect for affiliates.** Affiliates here are paid via
  PayPal / bank / manual ops — the engine records the payout but
  doesn't initiate the money movement. If you want auto-transfer via
  Stripe Connect to affiliates' accounts, use the
  `stripe_connect_multivendor` template in this lib and adapt its
  Partner model to be an Affiliate.
- **Multi-currency.** Mixed-currency shops are out of scope —
  `SHOP_DEFAULT_CURRENCY` is shop-wide. You can store different
  currencies on different Products (the field is there) but the cart
  enforces single-currency.
- **Inventory reservations during checkout.** Stock is checked when
  adding to cart but not held during the Stripe-confirm window. A
  popular variant can oversell if two customers checkout
  simultaneously. Add a 5-minute reservation row (`Reservation(variant,
  qty, expires_at)`) if your inventory is tight.
- **Bundled / configurable products.** One Variant → one SKU. Bundles
  (buy A + B for one price) need a separate model.
- **Refund-to-store-credit.** All refunds go back to the original
  payment method. Store credit is a wallet feature out of scope.
- **GraphQL.** REST only.

## Testing

```bash
pytest apps/shop_engine/tests/
```

The conftest stubs the `stripe` SDK so tests run without the package.
Provider tests pin both the local (fully working) and stub (raises
`NotImplementedError`) surfaces.

## Synergies with other templates in this lib

- **`notifications_multichannel`** — wire it into `Order.post_save`
  for order-confirmation / shipped / refunded emails, and override
  `tasks.send_affiliate_payout_notification` for payout receipts.
- **`stripe_connect_multivendor`** — drop this in alongside if you
  want auto-Connect transfers to partners/affiliates instead of
  manual ops. The Affiliate model here parallels its Partner model.
- **`saas_billing_credits_quota`** — pair if your product also sells
  credit packs; the engine's Stripe checkout is independent of the
  billing's subscriptions.
- **`hashed_api_tokens`** — if you ever expose the admin API to
  third-party tools (3PL integrations), token-auth them through that.
- **`legal_cms_pages`** — host /terms/, /privacy/, /shipping/ from
  there; link from your checkout footer.
