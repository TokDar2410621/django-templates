# newsletter-engine

═════════════════════════════════════════════
Template : newsletter-engine
Version  : 1.0.0
Mode     : CREATE (inspired by blog-dashboard's Lead/LeadEmailSent funnel)
Stack    : Django 5+ / DRF / Resend / Celery / (unfold optional)
Deps     : `requests`, `djangorestframework`, `celery` (optional at runtime)
Used by  : (none yet — first integration)
═════════════════════════════════════════════

A multi-tenant SaaS newsletter platform — the self-hosted Mailchimp/Brevo
subset most projects actually need: multi-list per tenant, tag/segment
filtering, drip automations with per-step conditions, open/click tracking
via pixel + redirect, double opt-in, RFC 8058 one-click unsubscribe,
Resend-driven bounce/complaint handling, and Loi 25 / RGPD-friendly consent
audit.

## Why this template

- **Multi-tenant by default.** Every owned row carries a ``tenant`` FK to
  the model named by ``NEWSLETTER_TENANT_MODEL`` (default ``AUTH_USER_MODEL``).
  Drop in a custom ``Organization`` model and resolver and the whole engine
  scopes automatically.
- **Two-bucket sending pipeline.** ``send_campaign`` flips a row to
  ``sending`` and enqueues a Celery fan-out task that creates one
  ``Delivery`` row per recipient + batches the SMTP calls. The HTTP request
  returns immediately, so a "Send now" button on a 50k-subscriber list
  doesn't time out.
- **Segment DSL → ORM Q.** Subscribers can be filtered by a small,
  whitelisted JSON DSL — boolean trees, field comparisons, ``has_tag``,
  ``in_list``, ``opened_in_last_days``, ``clicked_in_last_days``,
  ``no_engagement_for_days``, time ranges. The compiler raises
  ``SegmentDSLError`` on anything it doesn't recognize, so a malformed
  filter can't accidentally widen the recipient set.
- **Drip automations with conditions.** ``Automation`` + ordered
  ``AutomationStep``s with ``delay_seconds`` relative to the previous step.
  Each step has an optional Segment-DSL condition — if it doesn't match the
  subscriber at execution time, the step is silently skipped (the
  enrollment still advances so we don't loop).
- **Open + click tracking, no SaaS dependency.** Open pixel = 1x1
  transparent GIF embedded in this module; click redirect = base64-encoded
  URL. ``rewrite_html_for_tracking`` rewrites every ``<a href>`` and
  injects the pixel right before ``</body>``. Disable globally with
  ``NEWSLETTER_TRACKING_ENABLED=False``.
- **RFC 8058 one-click unsubscribe.** Every send injects a fresh
  ``UnsubscribeToken`` into the ``List-Unsubscribe`` + ``List-Unsubscribe-Post``
  headers so Gmail / Apple Mail / Outlook get a one-click button. Tokens
  are scoped — ``"all"`` (global unsub), ``"list:<slug>"`` (per-list), or
  ``"campaign:<id>"`` (one-campaign suppression).
- **Resend-webhook driven bounce/complaint.** A signed webhook updates the
  ``Delivery`` row + writes a ``BounceEvent`` audit record. Hard bounces
  immediately suppress the subscriber; soft bounces decay back to zero
  after ``NEWSLETTER_BOUNCE_DECAY_DAYS`` of clean sending.
- **Loi 25 / RGPD audit anchor.** ``Subscriber.consented_marketing`` is
  required for marketing sends; the application is responsible for setting
  it truthfully (an unchecked tick-box stays False). Combined with the
  ``BounceEvent`` audit and the append-only ``UnsubscribeToken`` rows you
  have a complete consent + revocation trail.

## API

### Admin / internal (IsAuthenticated)

| Method | Path                                            | Purpose                                       |
|--------|-------------------------------------------------|-----------------------------------------------|
| any    | `/api/newsletter/subscribers/`                  | CRUD subscribers (tenant-scoped)              |
| POST   | `/api/newsletter/subscribers/bulk-add-to-list/` | `{subscriber_ids, list_id}`                   |
| any    | `/api/newsletter/lists/`                        | CRUD mailing lists                            |
| any    | `/api/newsletter/tags/`                         | CRUD tags                                     |
| any    | `/api/newsletter/segments/`                     | CRUD segments                                 |
| GET    | `/api/newsletter/segments/<id>/preview/`        | Count + 25-sub sample for a segment           |
| any    | `/api/newsletter/campaigns/`                    | CRUD campaigns                                |
| POST   | `/api/newsletter/campaigns/<id>/send/`          | Transition to sending + enqueue fan-out       |
| POST   | `/api/newsletter/campaigns/<id>/cancel/`        | Cancel pending deliveries                     |
| GET    | `/api/newsletter/campaigns/<id>/stats/`         | Live per-status counts from Deliveries        |
| any    | `/api/newsletter/automations/`                  | CRUD automations (steps nested, read-only)    |

### Public (no auth)

| Method | Path                              | Purpose                                              |
|--------|-----------------------------------|------------------------------------------------------|
| POST   | `/api/newsletter/subscribe/`      | `{email, list_slug?, name?, consented_marketing}`    |
| GET    | `/api/newsletter/confirm/?token=` | Confirm double-opt-in                                |
| GET/POST | `/api/newsletter/unsubscribe/?token=` | One-click unsubscribe (RFC 8058 compatible)    |
| GET    | `/api/newsletter/preferences/?token=` | List which lists the subscriber is on            |
| POST   | `/api/newsletter/preferences/`    | `{token, list_slugs}` — update memberships           |

### Tracking (no auth, hit by mail clients)

| Method | Path                                                 |
|--------|------------------------------------------------------|
| GET    | `/api/newsletter/track/open/<delivery_token>.gif`   |
| GET    | `/api/newsletter/track/click/<delivery_token>/?u=…` |

### Webhooks (no auth, HMAC-verified)

| Method | Path                              | Provider |
|--------|-----------------------------------|----------|
| POST   | `/api/newsletter/webhooks/resend/`| Resend   |

## Quickstart

```bash
pip install requests djangorestframework
# Optional but expected for any non-trivial deployment:
pip install celery redis django-unfold
```

Add to `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    # ...
    "rest_framework",
    "newsletter_engine",
]
```

Wire URLs:

```python
# config/urls.py
urlpatterns = [
    # ...
    path("api/newsletter/", include("newsletter_engine.urls")),
]
```

Migrate:

```bash
python manage.py migrate
```

Create your first list + campaign via the admin (`/admin/newsletter_engine/`):

1. **Mailing list** — give it a slug; the public subscribe form will reference
   that slug.
2. **Subscribe yourself** (POST `/api/newsletter/subscribe/`) and confirm via
   the token logged at INFO level (in dev with no Resend key).
3. **Compose a campaign** — pick a list, paste HTML, save as draft.
4. **Action → Send now** — the fan-out task creates Delivery rows + the
   batches enqueue. Watch `/api/newsletter/campaigns/<id>/stats/` for
   real-time progress.

See [SETTINGS.md](./SETTINGS.md) for the full configuration matrix +
required Celery beat schedule.

## Sending pipeline in detail

```
HTTP "Send now"
     |
     v
services.send_campaign(camp)
     |  Campaign.status -> "sending"
     v
tasks.fan_out_campaign.delay(campaign_id)         # Celery
     |
     v
services.campaigns.fan_out(camp)
     |  bulk_create Delivery rows (idempotent on (campaign, subscriber))
     |  split into batches of NEWSLETTER_BATCH_SIZE
     v
tasks.send_campaign_batch.delay(batch_ids)        # Celery, per batch
     |
     v
for delivery in batch:
    rewrite_html_for_tracking(html, delivery)     # pixel + click rewrite
    backend.send(...)                             # Resend HTTP
    update Delivery row + atomic increment Campaign counters
     |
     v
services.compute_campaign_stats(camp)
     |  if no pending/queued left -> Campaign.status -> "sent"
```

A worker crash mid-batch leaves Delivery rows in their last known status —
the next batch retry sees them and finishes.

## Segment DSL

`Segment.filters` is a JSON tree. The compiler ``segment_dsl.compile_to_q``
turns it into a Django ``Q``. Supported ops:

```json
{"op": "and", "children": [...]}
{"op": "or",  "children": [...]}
{"op": "not", "child":    {...}}

{"op": "field", "field": "<name>", "compare": "eq|neq|in|gt|gte|lt|lte|contains|icontains|isnull", "value": <any>}
{"op": "has_tag",  "tag_id": <int>}
{"op": "in_list",  "list_id": <int>}

{"op": "opened_in_last_days",    "campaign_id": <int|null>, "days": <int>}
{"op": "clicked_in_last_days",   "campaign_id": <int|null>, "days": <int>}
{"op": "no_engagement_for_days", "days": <int>}

{"op": "subscribed_after",  "date": "YYYY-MM-DD"}
{"op": "subscribed_before", "date": "YYYY-MM-DD"}
```

Example — "active subscribers tagged VIP who haven't opened anything in 60
days":

```json
{
    "op": "and",
    "children": [
        {"op": "field", "field": "status", "compare": "eq", "value": "confirmed"},
        {"op": "has_tag", "tag_id": 5},
        {"op": "no_engagement_for_days", "days": 60}
    ]
}
```

Field whitelist is enforced in ``segment_dsl.ALLOWED_FIELDS`` — you can't
filter on arbitrary attributes (including sensitive ones).

## Integration with notifications-multichannel

If your project also uses the ``notifications-multichannel`` template, you
can route newsletter sends through its ``send_email`` helper so all email
goes through one channel (role-based senders, single Reply-To routing,
unified log). Write a small adapter backend:

```python
# myproject/newsletter_adapter.py
from notifications_multichannel.services import send_email
from newsletter_engine.backends.base import EmailBackend, SendResult

class MultichannelBackend(EmailBackend):
    def send(self, *, to, subject, html, text="", from_email,
             reply_to="", headers=None) -> SendResult:
        result = send_email(
            user=None,   # newsletter sends are to subscribers, not users
            to=to,
            role="newsletter",
            subject=subject,
            html=html,
            text=text,
            reply_to=reply_to,
        )
        return SendResult(
            status=result.status,
            provider_message_id=result.provider_message_id,
            error=result.error,
        )
```

Then set ``NEWSLETTER_EMAIL_BACKEND = "myproject.newsletter_adapter.MultichannelBackend"``.

## Customization hooks

- ``NEWSLETTER_TENANT_MODEL`` — dotted path to the tenant model (default `AUTH_USER_MODEL`)
- ``NEWSLETTER_TENANT_RESOLVER`` — dotted path to a `request -> tenant` callable
- ``NEWSLETTER_EMAIL_BACKEND`` — dotted path to the backend class
- ``NEWSLETTER_DEFAULT_FROM_EMAIL`` / ``NEWSLETTER_DEFAULT_REPLY_TO``
- ``NEWSLETTER_DOUBLE_OPT_IN`` — default `True`
- ``NEWSLETTER_TRACKING_BASE_URL`` — required for tracking to work
- ``NEWSLETTER_TRACKING_ENABLED`` — global on/off
- ``NEWSLETTER_AUTOMATION_TRIGGERS`` — custom trigger choices
- ``NEWSLETTER_BATCH_SIZE`` — default 100
- ``NEWSLETTER_BOUNCE_THRESHOLD`` — soft-bounces before auto-suppress (default 3)
- ``NEWSLETTER_BOUNCE_DECAY_DAYS`` — clean-sending days before counter resets (default 30)
- ``NEWSLETTER_CONFIRM_REDIRECT_URL`` / ``NEWSLETTER_UNSUBSCRIBE_REDIRECT_URL``

## Testing

```bash
pytest apps/newsletter_engine/tests/
```

The conftest force-binds the email backend to ``DummyBackend`` (in-memory
list of sent messages) and resets it between tests, so assertions on
"what got sent" are deterministic and require no network.

## What this does NOT include

- **A campaign HTML editor / drag-and-drop builder.** Bring your own
  (Beefree, MJML, Unlayer, hand-written templates). The admin uses a
  plain textarea — the same trade-off as legal-cms-pages — because the
  right editor depends on the project's content team.
- **Provider abstraction beyond Resend.** A second backend (Postmark,
  SES, Sendgrid) is a single file in ``backends/``; we ship Resend +
  Dummy because that's what every reference project uses. PRs welcome.
- **Bounce-classification ML.** Hard vs soft mapping uses Resend's event
  types. If you need finer-grained classification (transient SPF failure
  vs deliberate block), parse the raw SMTP response in
  ``services.mark_bounced``.
- **Per-link UTM auto-tagging.** ``rewrite_html_for_tracking`` rewrites
  hrefs to go through our redirect; it does NOT inject `utm_*` params. Add
  that in your HTML composer or before passing the body in.
- **Subscriber import via CSV file.** The admin's bulk-add action takes
  IDs; a CSV importer is a 30-line management command but the schema you
  want is product-specific. Write one against ``services.subscribe`` and
  call it a day.
- **Localized email templates.** Bring your own. Pass per-locale HTML to
  the campaign + segment by ``locale`` to send the right variant to the
  right cohort.
- **Tracking on automation step emails.** The campaign path rewrites HTML
  via ``rewrite_html_for_tracking``; the automation step path currently
  sends raw HTML. Outstanding TODO — see below.
