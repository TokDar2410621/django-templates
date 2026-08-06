# SETTINGS — qr-tag-activation-batches

## pip dependencies

```
djangorestframework>=3.14
celery>=5.3
Pillow>=10.0
```

Optional:

```
django-unfold        # if your admin uses Unfold; otherwise falls back to stock ModelAdmin
```

## INSTALLED_APPS

```python
INSTALLED_APPS = [
    # ...
    "django.contrib.contenttypes",   # required for the GenericForeignKey
    "rest_framework",
    "qr_tag_activation_batches",
]
```

## URLs

```python
# config/urls.py
from django.urls import include, path
from qr_tag_activation_batches.urls import api_urlpatterns, scan_urlpatterns

urlpatterns = [
    # ...
    path("",                  include(scan_urlpatterns)),   # GET /q/<slug>/
    path("api/activation/",   include(api_urlpatterns)),    # full API
]
```

## Configurable settings (all optional)

```python
# settings.py — all knobs below have sensible defaults; override as needed

# How many digits in the activation code printed on the carton/scratch-off.
# Stored as a CharField (no leading-zero suppression). Default 6.
ACTIVATION_CODE_LENGTH = 6

# Hard upper bound on a single batch — protects the bulk insert + CSV
# export. Default 10 000. Set higher only if you have measured that your
# DB can handle it.
ACTIVATION_BATCH_MAX_SIZE = 10000

# Length of the slug encoded in the QR. 8 chars over [a-z0-9] gives a
# keyspace of ~2.8 trillion — plenty for any realistic SKU volume.
QR_SLUG_LENGTH = 8

# Distribution channels. Override to add custom kinds without a
# migration; ``kind`` is CharField(max_length=32).
ACTIVATION_BATCH_KINDS = [
    ("b2c_retail",  "B2C — direct retail sale"),
    ("b2b_partner", "B2B — partner (school, manufacturer)"),
    ("internal",    "Internal (test, demo, marketing)"),
    ("affiliate",   "Affiliate-distributed"),   # example custom kind
]

# Physical tag forms. Override to add formats.
ACTIVATION_TAG_FORMATS = [
    ("sticker",   "Vinyl sticker"),
    ("patch",     "Fabric patch"),
    ("hang_tag",  "Hang tag"),
    ("keychain",  "Keychain"),
    ("nfc_card",  "NFC + QR combo card"),       # example custom format
]

# Photo-claim dispute window. After this many hours with no dispute, the
# code's ``claim_status`` flips from PROVISIONAL → CONFIRMED. Default 48.
ACTIVATION_PROVISIONAL_HOURS = 48

# Optional callable to extend the slug-uniqueness guard. Called as
# ``guard(slug) -> bool`` during batch generation. Return True if the
# slug is already used by your own domain model (e.g. an in-flight Item
# already references that slug).
def my_extra_slug_guard(slug: str) -> bool:
    from myapp.models import Sticker
    return Sticker.objects.filter(qr_slug=slug).exists()

ACTIVATION_EXTRA_SLUG_GUARD = my_extra_slug_guard

# Base URL injected into the exported CSV (qr_slug → public_url column).
# Falls back to "" (relative path) if unset.
FRONTEND_URL = "https://www.example.com"
```

## Celery wiring

```python
# config/celery.py
from celery.schedules import crontab

app.conf.beat_schedule = {
    "qr-tag-confirm-provisional-claims": {
        "task": "qr_tag_activation_batches.confirm_provisional_claims",
        "schedule": crontab(minute=0),   # every hour
    },
}
```

## Env vars

None required by the template itself. `FRONTEND_URL` is usually pulled
from `os.environ` by your config layer, but the activation app reads it
through Django settings.

## Post-install verification

```bash
python manage.py check
python manage.py migrate
pytest apps/qr_tag_activation_batches/tests/

# curl smoke (after generating a batch via the admin):
curl -s http://127.0.0.1:8000/q/abcd1234/   # public scan endpoint
# expect {"qr_slug":"abcd1234","found":true,"claimable":true,...}

# Authenticated claim (token in $TOKEN):
curl -s -X POST http://127.0.0.1:8000/api/activation/claim/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"qr_slug":"abcd1234","activation_code":"123456"}'
```
