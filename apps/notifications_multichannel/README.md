# notifications-multichannel

═════════════════════════════════════════════
Template : notifications-multichannel
Version  : 1.0.0
Mode     : EXTRACT-A
Source   : FIN/apps/notifications
Stack    : Django 5+ / DRF / Resend / pywebpush / Twilio / (unfold optional)
Deps     : `resend>=2.0` *(or just `requests`)*, `pywebpush>=2.0`, `twilio>=8.0`, `djangorestframework`
Used by  : (none yet)
═════════════════════════════════════════════

Unified service layer for the three transactional channels every consumer
app eventually needs: **email** (Resend), **Web Push** (VAPID via
pywebpush), and **SMS** (Twilio). One facade, role-based email senders,
opt-in delivery logs, and degraded-mode fallbacks so missing API keys
never crash the boot.

## Why this template

- **Single facade, three providers.** `send(user, channel, ...)` routes
  to the right backend. Channel-specific helpers (`send_email`,
  `send_push`, `send_sms`) are available when you need their full
  argument surface.
- **Role-based email senders.** Pick `noreply` / `notification` /
  `orders` per send. Each address lives in its own Gmail filter and gets
  its own `Reply-To`, so transactional and marketing footers don't
  collide. (Pattern proven on SendMeNow + Find It Now production.)
- **Degraded mode by default.** Every backend returns
  `SendResult(status='skipped')` when its API key is empty — the rest of
  the app keeps booting and you ship the missing key when you have it.
- **Auto-prunes dead push subs.** A 410-gone response from the push
  service deletes the row immediately so the table doesn't accumulate
  stale subscriptions after browser uninstalls.
- **PEM env-var handling.** VAPID private keys arrive from Railway/Heroku
  as single-line strings with literal `\n` escapes — we restore the
  newlines at runtime. No more "invalid PEM" boots.
- **Templated emails.** Pass `html`/`text` directly OR
  `template_name="email/foo"` + `context={...}` to render via Django's
  template engine. Both `.html` and `.txt` variants resolve auto.
- **Opt-in delivery log.** Every send writes a `NotificationLog` row
  (status, provider id, error) visible in the admin. Disable with
  `NOTIFICATIONS_LOG_DELIVERIES = False` for compliance or storage.

## Channel matrix

| Channel  | Backend       | Provider | Degraded when             | Provider id    |
|----------|---------------|----------|---------------------------|----------------|
| email    | `email_resend`| Resend   | `RESEND_API_KEY` empty    | Resend msg id  |
| push     | `push_webpush`| pywebpush| `VAPID_*` keys empty      | n/a (per sub)  |
| sms      | `sms_twilio`  | Twilio   | `TWILIO_*` creds empty    | Twilio SID     |

## API

| Method | Path                                          | Auth        | Purpose                                  |
|--------|-----------------------------------------------|-------------|------------------------------------------|
| POST   | `/api/notifications/push/subscribe/`          | user        | Register a Web Push subscription          |
| POST   | `/api/notifications/push/unsubscribe/`        | user        | Drop a subscription by endpoint           |
| POST   | `/api/notifications/test/`                    | admin       | Send a hello on email/push/sms (self)     |

## Quickstart

```bash
pip install requests pywebpush twilio djangorestframework
```

Add to `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    # ...
    "rest_framework",
    "notifications_multichannel",
]
```

Wire URLs:

```python
# config/urls.py
urlpatterns = [
    # ...
    path("api/notifications/", include("notifications_multichannel.urls")),
]
```

Migrate:

```bash
python manage.py migrate
```

Send something from anywhere in your code:

```python
from notifications_multichannel.services import send_email, send_push, send_sms

send_email(
    user=user,
    role="orders",
    subject="Your order is on the way",
    template_name="emails/order_shipped",     # renders .html + .txt
    context={"order": order, "tracking_url": url},
)

send_push(
    user=user,
    title="New message",
    body="You have 1 unread reply",
    url="/inbox",
)

send_sms(user=user, body="Your verification code is 482103")
```

Or pick the channel dynamically:

```python
from notifications_multichannel.services import send

for channel in user_prefs.enabled_channels:
    send(user=user, channel=channel, subject="Hi", html="<p>Hi</p>")
```

## Degraded mode behavior

Each `send_*` helper returns a `SendResult`:

```python
@dataclass
class SendResult:
    status: str                   # "sent" | "skipped" | "failed"
    provider_message_id: str = ""
    error: str = ""
    meta: dict = field(default_factory=dict)
```

- `status="skipped"` → provider not configured (API key empty, no push
  subscriptions, etc.). **Not an error** — your app keeps working.
- `status="failed"` → provider rejected the request or network blew up.
  Inspect `error` for diagnostics. The `NotificationLog` row holds the
  same info for the admin.
- `status="sent"` → enjoy. `provider_message_id` is your audit anchor.

Callers should treat `result.ok` (True only on `"sent"`) as the success
boolean — never assume "no exception = sent", because backends never
raise.

## Push subscription lifecycle

```text
Browser                Backend
   |   subscribe + keys   |
   |--------------------->|  POST /api/notifications/push/subscribe/
   |                      |     → PushSubscription.objects.update_or_create
   |                      |
   |   (some time later)  |
   |       send_push      |
   |                      |  pywebpush → Mozilla / FCM / APNs gateway
   |<---- payload --------|
   |                      |
   |  unsubscribe         |
   |--------------------->|  POST /api/notifications/push/unsubscribe/
                          |     → row deleted
```

Browser-side, when `pushManager.permissionState` flips to "denied" the
endpoint returns 410 on the next push and we auto-prune the row. The
client doesn't need to call unsubscribe.

## Customization hooks

- `RESEND_SENDERS` / `RESEND_REPLY_TO` — role-based email config
- `NOTIFICATIONS_LOG_DELIVERIES` — bool, default `True`
- `NOTIFICATIONS_USER_PHONE_ATTR` — name of the phone field on the user
  model (default `"phone_e164"`)
- `NOTIFICATIONS_SMS_MAX_LEN` — int, default 320 (= 2 SMS segments)
- `NOTIFICATIONS_PUSH_DEFAULT_ICON` — path/URL passed when caller omits
  `icon` (default `/static/icons/192.png`)

## Testing

```bash
pytest apps/notifications_multichannel/tests/
```

The conftest mocks each provider SDK so tests are hermetic and run
without network access.

## What this does NOT include

- **Per-user channel preferences (toggles).** The source app shipped a
  `NotificationPrefs` model, but the right shape depends on your product
  (granular event toggles? quiet hours? unsubscribe links?). Add a
  domain-specific prefs table that calls `send_*` only when its toggle
  is on.
- **Open/click tracking.** Resend and Twilio publish webhook events for
  delivery + opens; wire them to update `NotificationLog` if you care.
- **Inbound email/SMS routing.** Out of scope; this is transactional
  send-only.
- **Rate limiting.** A misbehaving caller could send thousands per
  minute. Wrap the service in your project's existing throttle decorator
  or Celery task.
- **Localized templates.** Bring your own. Pass the right `template_name`
  per locale, or use `django.utils.translation` inside your template.
