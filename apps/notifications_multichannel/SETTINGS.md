# SETTINGS — notifications-multichannel

## pip dependencies

```
djangorestframework>=3.14
requests>=2.31              # used by the Resend HTTP backend
pywebpush>=2.0              # Web Push (VAPID)
twilio>=8.0                 # SMS
```

Optional:

```
django-unfold               # if your admin uses Unfold; otherwise falls back to stock ModelAdmin
```

> `pywebpush` and `twilio` are imported **lazily**. If a project doesn't
> use one of them, you can omit the dependency and the matching backend
> degrades gracefully (returns `status="skipped"`).

## INSTALLED_APPS

```python
INSTALLED_APPS = [
    # ...
    "rest_framework",
    "notifications_multichannel",
]
```

## URLs

```python
# config/urls.py
from django.urls import path, include

urlpatterns = [
    # ...
    path("api/notifications/", include("notifications_multichannel.urls")),
]
```

## Env vars

### Email — Resend

```env
RESEND_API_KEY=re_xxxxx
RESEND_FROM_EMAIL=noreply@example.com        # generic fallback if a role has no sender

# Role-based senders (recommended over the single fallback above)
RESEND_FROM_NOREPLY=noreply@example.com
RESEND_FROM_NOTIFICATION=notification@example.com
RESEND_FROM_ORDERS=orders@example.com

# Optional Reply-To overrides (per role)
RESEND_REPLY_TO_ORDERS=support@example.com
```

```python
# settings.py
RESEND_API_KEY = env("RESEND_API_KEY", default="")
RESEND_FROM_EMAIL = env("RESEND_FROM_EMAIL", default="")
RESEND_SENDERS = {
    "noreply":      env("RESEND_FROM_NOREPLY", default=""),
    "notification": env("RESEND_FROM_NOTIFICATION", default=""),
    "orders":       env("RESEND_FROM_ORDERS", default=""),
}
RESEND_REPLY_TO = {
    "noreply": "",
    "notification": "",
    "orders": env("RESEND_REPLY_TO_ORDERS", default=""),
}
```

You can add custom roles (e.g. `marketing`, `support`) by appending keys
to both dicts — callers just pass `role="support"` to `send_email`.

### Web Push — VAPID

Generate a VAPID keypair once (e.g. `npx web-push generate-vapid-keys`)
and stash the values in env. The private key is a PEM block; paste it as
a single line with literal `\n` escapes for the newlines — the backend
restores them at runtime.

```env
VAPID_PUBLIC_KEY=BJxxxxxx
VAPID_PRIVATE_KEY=-----BEGIN PRIVATE KEY-----\nMIGHA...\n-----END PRIVATE KEY-----
VAPID_ADMIN_EMAIL=admin@example.com
```

```python
# settings.py — un-escape the PEM at boot so Railway env-vars work
_priv = env("VAPID_PRIVATE_KEY", default="")
VAPID_PUBLIC_KEY  = env("VAPID_PUBLIC_KEY", default="")
VAPID_PRIVATE_KEY = _priv.replace("\\n", "\n") if _priv else ""
VAPID_ADMIN_EMAIL = env("VAPID_ADMIN_EMAIL", default="")
```

> The backend ALSO un-escapes on its own as a safety net, so projects
> using older settings modules without the `replace("\\n", "\n")` line
> still work.

### SMS — Twilio

```env
TWILIO_ACCOUNT_SID=ACxxxxxx
TWILIO_AUTH_TOKEN=secret
TWILIO_FROM_NUMBER=+15551234567
```

```python
TWILIO_ACCOUNT_SID = env("TWILIO_ACCOUNT_SID", default="")
TWILIO_AUTH_TOKEN  = env("TWILIO_AUTH_TOKEN", default="")
TWILIO_FROM_NUMBER = env("TWILIO_FROM_NUMBER", default="")
```

### Tuning

All optional, with sensible defaults:

```python
# Disable the NotificationLog table if you don't want per-send audit rows.
NOTIFICATIONS_LOG_DELIVERIES = True

# Name of the phone-number attribute on your user model (used by
# send_sms when caller omits to_e164). Default: "phone_e164".
NOTIFICATIONS_USER_PHONE_ATTR = "phone_e164"

# Max SMS body length before truncation. Default: 320 (2 segments).
NOTIFICATIONS_SMS_MAX_LEN = 320

# Default icon URL passed in the push payload when caller omits one.
NOTIFICATIONS_PUSH_DEFAULT_ICON = "/static/icons/192.png"
```

## Post-install verification

```bash
python manage.py check
python manage.py migrate
pytest apps/notifications_multichannel/tests/

# Smoke (authenticated user):
curl -s -X POST http://127.0.0.1:8000/api/notifications/push/subscribe/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"endpoint":"https://example.com/a","keys":{"p256dh":"k","auth":"a"}}'

# Smoke (admin, hits all three providers in degraded mode = all skipped):
curl -s -X POST http://127.0.0.1:8000/api/notifications/test/ \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"email":true,"push":true,"sms":false}'
```
