# SETTINGS — newsletter-engine

## pip dependencies

```
requests>=2.31
djangorestframework>=3.14
```

Strongly recommended (you'll hit these eventually):

```
celery>=5.3              # async fan-out + beat-scheduled tasks
redis>=5.0               # Celery broker + result backend
django-unfold            # if your admin uses Unfold; otherwise stock ModelAdmin
```

## INSTALLED_APPS

```python
INSTALLED_APPS = [
    # ...
    "rest_framework",
    "newsletter_engine",
]
```

## URLs

```python
# config/urls.py
from django.urls import path, include

urlpatterns = [
    # ...
    path("api/newsletter/", include("newsletter_engine.urls")),
]
```

## Configurable settings (all optional)

```python
# settings.py — all settings below have sensible defaults; override as needed

# ---------------------------------------------------------------------------
# Multi-tenancy
# ---------------------------------------------------------------------------

# Dotted path to the model that "owns" subscribers / lists / campaigns.
# Default = AUTH_USER_MODEL — i.e. one user is one tenant. For multi-tenant
# SaaS, point this at your Organization model.
NEWSLETTER_TENANT_MODEL = "myapp.Organization"

# Optional callable that resolves a tenant from a request. If unset, views
# default to `request.user`. Signature: `request -> tenant_instance`.
NEWSLETTER_TENANT_RESOLVER = "myapp.resolvers.tenant_from_subdomain"

# ---------------------------------------------------------------------------
# Email backend
# ---------------------------------------------------------------------------

# Dotted path to the class implementing newsletter_engine.backends.base.EmailBackend.
# Default = newsletter_engine.backends.resend.ResendBackend
NEWSLETTER_EMAIL_BACKEND = "newsletter_engine.backends.resend.ResendBackend"

# Required by Resend backend. Falls back to RESEND_API_KEY if unset.
NEWSLETTER_RESEND_API_KEY = "re_xxx"

# Default sender when the campaign / list doesn't override.
NEWSLETTER_DEFAULT_FROM_EMAIL = "newsletter@your-domain.com"

# Default Reply-To when the campaign / list doesn't override.
NEWSLETTER_DEFAULT_REPLY_TO = "hello@your-domain.com"

# ---------------------------------------------------------------------------
# Opt-in flow
# ---------------------------------------------------------------------------

# Default for newly-created lists (each list can override via its
# `requires_double_opt_in` column).
NEWSLETTER_DOUBLE_OPT_IN = True

# Confirmation tokens currently never expire in the DB. If you want them
# to, expose this in your own cron + sweep stale UnsubscribeToken rows.
NEWSLETTER_CONFIRMATION_EXPIRY_HOURS = 48  # not yet enforced; documented for parity

# Optional frontend redirects after confirm / unsubscribe. If unset, the
# endpoints return a JSON body.
NEWSLETTER_CONFIRM_REDIRECT_URL = "https://your-frontend.com/newsletter/confirmed"
NEWSLETTER_UNSUBSCRIBE_REDIRECT_URL = "https://your-frontend.com/newsletter/goodbye"

# ---------------------------------------------------------------------------
# Tracking
# ---------------------------------------------------------------------------

# Public base URL of YOUR backend. Required for pixel + click-redirect URLs
# to resolve. Fallback: FRONTEND_BASE_URL.
NEWSLETTER_TRACKING_BASE_URL = "https://backend.your-domain.com"

# Global on/off. Useful for transactional-only deployments where you don't
# want any open/click tracking for privacy reasons.
NEWSLETTER_TRACKING_ENABLED = True

# ---------------------------------------------------------------------------
# Automations
# ---------------------------------------------------------------------------

# Override to add custom trigger types — used as choices on the
# Automation.trigger field. Schema: list[(value, label)].
NEWSLETTER_AUTOMATION_TRIGGERS = [
    ("signup",      "On subscriber signup"),
    ("list_joined", "When subscriber joins a list"),
    ("tag_added",   "When a tag is applied"),
    ("manual",      "Manual enrollment (admin/API)"),
    ("anniversary", "Anniversary (yearly)"),
    ("custom_trigger", "My custom trigger"),    # add as needed
]

# ---------------------------------------------------------------------------
# Sending pipeline
# ---------------------------------------------------------------------------

# Subscribers per Celery batch task. Tune to balance "throughput" (bigger =
# fewer task overhead) vs "blast-radius if a worker crashes" (smaller =
# less re-work).
NEWSLETTER_BATCH_SIZE = 100

# Soft-bounces before we auto-suppress a subscriber.
NEWSLETTER_BOUNCE_THRESHOLD = 3

# Days of clean sending before bounce_count decays back to zero.
NEWSLETTER_BOUNCE_DECAY_DAYS = 30

# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------

# Resend webhook signing secret (from the Resend dashboard).
NEWSLETTER_RESEND_WEBHOOK_SECRET = "whsec_xxx"
```

## Celery beat snippet

```python
# settings.py — copy into CELERY_BEAT_SCHEDULE

CELERY_BEAT_SCHEDULE = {
    # Advance automation enrollments whose next step is due. Every 5 min
    # gives a typical "J+1" / "J+7" drip cadence sub-minute precision per
    # subscriber.
    "newsletter-automation-tick": {
        "task": "newsletter_engine.tasks.process_automation_tick",
        "schedule": 300,
    },

    # Pick up campaigns scheduled in the past and kick off their fan-out.
    "newsletter-scheduled-campaigns": {
        "task": "newsletter_engine.tasks.process_scheduled_campaigns",
        "schedule": 60,
    },

    # Decay bounce_count after clean sending. Daily is fine.
    "newsletter-bounces-decay": {
        "task": "newsletter_engine.tasks.process_bounces_decay",
        "schedule": 86400,
    },
}
```

If your project doesn't use Celery, the tasks decorator falls back to a
no-op passthrough — but you'll have to call ``services.send_campaign`` and
``services.fan_out`` from a management command yourself.

## Env vars

| Variable                              | Required for                  |
|---------------------------------------|-------------------------------|
| `NEWSLETTER_RESEND_API_KEY` (or `RESEND_API_KEY`) | Sending email via Resend |
| `NEWSLETTER_RESEND_WEBHOOK_SECRET`    | Validating Resend webhooks    |

Both are degraded-gracefully: missing them returns 503 from the affected
endpoint instead of crashing on boot.

## Post-install verification

```bash
python manage.py check
python manage.py migrate
pytest apps/newsletter_engine/tests/

# curl smoke (replace TOKEN with a real JWT/session cookie for the admin endpoints):
curl -s -X POST -H "Content-Type: application/json" \
  -d '{"email":"me@example.com","list_slug":"weekly","consented_marketing":true}' \
  http://127.0.0.1:8000/api/newsletter/subscribe/
# expected: 200 {"ok": true, "detail": "Subscription requested."}

curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8000/api/newsletter/lists/
# expected: 200 [...]
```

## Wiring with notifications-multichannel

Both templates ship a Resend-backed email sender. If you install both, you
have a choice:

- **Independent** (default) — newsletter_engine's ResendBackend talks to
  Resend directly; notifications_multichannel does the same for
  transactional. They share an API key but nothing else. Pro: minimal
  coupling. Con: two `RESEND_API_KEY` lookups (we honor both).

- **Unified** — write a small adapter so newsletter_engine routes through
  notifications_multichannel's role-based sender machinery. See the
  example in README.md → "Integration with notifications-multichannel".
  Recommended for projects already using role-based senders, because Gmail
  filter rules + Reply-To routing apply to newsletter sends too.
