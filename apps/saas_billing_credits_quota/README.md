# saas-billing-credits-quota

═════════════════════════════════════════════
Template : saas-billing-credits-quota
Version  : 1.0.0
Mode     : EXTRACT-A
Source   : blog-dashboard/backend/sites_mgmt
Stack    : Django 5+ / DRF / Stripe / (unfold optional)
Deps     : `stripe>=10`, `djangorestframework`
Used by  : (none yet — first integration)
═════════════════════════════════════════════

Per-user subscriptions + top-up credits + monthly resource quotas, with a
Stripe webhook handler that mirrors plan state into your DB and applies
one-time credit purchases atomically.

## Why this template

- **Two budgets, one consume call.** ``services.consume(user, "article_generation")``
  charges the plan's monthly quota first; falls back to top-up credits only
  when the plan is exhausted. Callers don't have to think about which bucket
  to debit — the return value (``"quota"`` vs ``"credit"``) tells them what
  was used.
- **Generic resource keys.** The original blog-dashboard hard-coded
  `articles_per_month`. This template generalizes to `(plan, resource_key) → limit`,
  so the same machinery bills article generation, API calls, exports, etc.
  with the same code path.
- **Webhook idempotency built in.** ``add_credits(..., stripe_session_id=...)``
  short-circuits on duplicate purchase events. Stripe re-delivers webhooks
  on flaky network — without idempotency you'd double-credit every retry.
- **Atomic mutations.** Credit balance and monthly counters are updated
  with `F()` expressions inside a single UPDATE so concurrent consume calls
  from different workers can't race. `_atomic_debit` filters on
  `balance__gte=amount` so the balance can never go negative even under load.
- **Append-only ledger.** Every credit movement (purchase/spend/refund/gift)
  is logged in `CreditTransaction`. `sum(amount)` always equals
  `CreditBalance.balance` — the admin surfaces drift in red so support sees
  it before the customer does.

## API

| Method | Path                          | Auth          | Purpose                                          |
|--------|-------------------------------|---------------|--------------------------------------------------|
| GET    | `/api/billing/me/`            | IsAuthenticated | Current plan, status, usage, balance, recent txns |
| POST   | `/api/billing/consume/`       | IsAuthenticated | `{resource_key, n=1}` → `"quota"`/`"credit"` or 402 |
| POST   | `/api/billing/checkout/`      | IsAuthenticated | `{mode: "subscription"\|"payment", sku}` → Stripe URL |
| POST   | `/api/billing/stripe/webhook/` | none (HMAC)  | Stripe event ingestion — register this URL on Stripe |

## Quickstart

```bash
pip install stripe>=10 djangorestframework
```

Add to `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    # ...
    "rest_framework",
    "saas_billing_credits_quota",
]
```

Wire URLs:

```python
# config/urls.py
urlpatterns = [
    # ...
    path("api/billing/", include("saas_billing_credits_quota.urls")),
]
```

Configure your plans + Stripe price IDs in settings (see [SETTINGS.md](./SETTINGS.md)).

Migrate:

```bash
python manage.py migrate
```

Smoke test:

```bash
# Get current state (creates the user's Subscription on first call)
curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8000/api/billing/me/ | jq

# Try to consume an article generation
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"resource_key": "article_generation", "n": 1}' \
  http://127.0.0.1:8000/api/billing/consume/ | jq
```

## Consume model in detail

```
consume(user, resource_key, n=1):
    plan = user.subscription.plan
    limit = SAAS_PLAN_LIMITS[plan][resource_key]   # None = unlimited

    if limit is None:
        increment monthly counter; return "quota"
    if monthly_count(user, resource_key) + n <= limit:
        increment monthly counter; return "quota"
    if atomic_debit(user, n) succeeds:
        log spend txn; return "credit"
    raise QuotaExceeded
```

The whole thing runs in a single transaction. ``QuotaExceeded`` carries
``resource_key``, ``plan_limit``, ``current_count``, ``credits_available`` and
``requested`` so the HTTP layer can return a structured 402 payload that the
frontend uses to render the right upgrade CTA.

## Integration with billing-aware features

Any code path that calls a third-party API on the user's behalf should sit
behind ``consume``. Example wiring an Anthropic AI call:

```python
from saas_billing_credits_quota.exceptions import QuotaExceeded
from saas_billing_credits_quota.services import consume

def generate_article(user, prompt: str) -> Article:
    try:
        bucket = consume(user, "article_generation", n=1)
    except QuotaExceeded:
        raise PermissionDenied("Upgrade your plan or buy credits to continue.")
    # ... actual Anthropic call ...
    article = anthropic_client.generate(prompt)
    log.info("article generated bucket=%s user=%s", bucket, user.pk)
    return article
```

The pattern works the same for any per-call billable: image generation,
data exports, transcriptions, etc.

## Stripe setup

1. Create Products + Prices in the Stripe dashboard (one Price per plan +
   one per credit pack).
2. Drop the Price IDs in env vars matching your `SAAS_PLAN_STRIPE_PRICES`
   and `SAAS_CREDIT_PACKS` config.
3. Register the webhook endpoint:
   `https://yourdomain/api/billing/stripe/webhook/` (subscribe to
   `customer.subscription.*`, `invoice.payment_*`, `checkout.session.completed`).
4. Drop the webhook signing secret in `STRIPE_WEBHOOK_SECRET`.

## Testing

```bash
pytest apps/saas_billing_credits_quota/tests/
```

The concurrency test in `test_atomic_increment.py` is skipped on SQLite and
only runs against Postgres — set your `DATABASES` to a scratch Postgres
instance to exercise the race-condition guard for real.

## Customization hooks

- `SAAS_PLAN_CHOICES` — list[(slug, label)] of plans accepted by the
  Subscription.plan field
- `SAAS_DEFAULT_PLAN` — slug assigned to new subscriptions (default `"free"`)
- `SAAS_PLAN_LIMITS` — nested dict `{plan_slug: {resource_key: limit_or_None}}`
- `SAAS_PLAN_STRIPE_PRICES` — `{plan_slug: env_var_name}` mapping for
  subscription Price IDs
- `SAAS_CREDIT_PACKS` — `{pack_slug: {credits, env, label}}` for one-time
  packs
- `SAAS_CHECKOUT_RETURN_PATH` — frontend path Stripe redirects to after
  checkout (default `"/billing"`)
- `current_month_key()` is a module-level function in `services.py` — patch
  it if your billing cycle doesn't align with calendar months.

## What this does NOT include

- **Stripe Connect / multi-tenant payouts.** This template assumes one
  Stripe account collecting all revenue. If you need to split payouts to
  affiliates or marketplace sellers, layer that on top.
- **Proration / mid-cycle plan changes.** We mirror Stripe's view of the
  world; Stripe handles proration when you call the Customer Portal. There's
  no in-app "upgrade now and credit the unused portion" UI helper.
- **Trial expiry job.** Stripe sends `customer.subscription.updated` with
  `status="active"` when a trial ends — we already react to that. But we
  don't proactively expire dangling trials in our DB if Stripe never sends
  the event (very rare in practice).
- **Email notifications.** When a payment fails (`past_due`), this template
  marks the row but doesn't email anyone. Plug your notification stack on
  top: `mark_past_due` is the hook point.
- **Customer Portal endpoint.** The original blog-dashboard had a
  `BillingPortalView` — left out here because the implementation is two
  lines of `stripe.billing_portal.Session.create(...)` that callers can
  copy-paste.
