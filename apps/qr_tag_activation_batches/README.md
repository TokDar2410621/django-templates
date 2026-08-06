# qr-tag-activation-batches

═════════════════════════════════════════════
Template : qr-tag-activation-batches
Version  : 1.0.0
Mode     : EXTRACT-A
Source   : FIN/apps/activation
Stack    : Django 5+ / DRF / Celery / (unfold optional)
Deps     : `djangorestframework`, `celery`, `Pillow`
Used by  : QR Code Agency (QrStudio_API/apps/claimable_qr)
═════════════════════════════════════════════

Pre-allocated batches of physical QR tags. The server generates N
`(qr_slug, activation_code)` pairs at batch-creation time; the slug is
encoded in the printed QR; the activation code is delivered separately
(scratch-off card, CSV file, or never — see `claim_mode`). Customers
scan the QR, type the code (or upload a proof photo), and the system
links the now-consumed tag to a caller-provided domain object.

## Why this template

- **Pre-allocation is non-negotiable for physical merch.** Once a sticker
  is printed, its slug is immutable. We allocate the slug at batch
  creation so the printing partner can print → ship → activate in any
  order.
- **Dual claim mode.** `CODE` (6-digit code printed separately, highest
  security) for B2B/B2C-with-card flows. `PHOTO` (no code; first
  scanner uploads a proof photo with a 48 h dispute window) for retail
  / factory-applied tags where a per-tag scratch-off isn't practical.
- **Domain-agnostic linking.** The activation code optionally links to
  ANY domain object via a GenericForeignKey (`linked_object_type` +
  `linked_object_id`). No hardcoded `Item` model — your project plugs in
  its own.
- **Transactional bulk insert.** A batch of 5000 codes runs as a single
  transaction with `bulk_create(batch_size=500)`. The slug-uniqueness
  guard re-rolls on collision (rare in 36⁸ keyspace).
- **Configurable cap.** `ACTIVATION_BATCH_MAX_SIZE` keeps a single batch
  bounded — default 10 000.

## Flow diagram

```
┌──────────┐                       ┌──────────┐                       ┌────────────┐
│  Admin   │── generate_batch() ──▶│  Server  │── bulk_create(N) ────▶│ ActivationCode │
└──────────┘                       └────┬─────┘                       └────┬───────┘
                                        │                                   │
                                        ▼ export CSV                       │ (codes
                                  ┌──────────┐                              │  printed
                                  │ Partner  │                              │  on physical
                                  │ printer  │── tags shipped ──▶ Customer │  tags)
                                  └──────────┘                              │
                                                                            │
Customer scans QR (slug only) ──▶ GET /q/<slug>/ ──▶ "claim me"             │
Customer enters code         ──▶ POST /api/activation/claim/ ──▶ claim_code()
                                                                   │
                                                                   ▼
                                                          ActivationCode marked
                                                          consumed + linked_object
```

## API

| Method | Path                                | Auth      | Purpose                                |
|--------|-------------------------------------|-----------|----------------------------------------|
| GET    | `/q/<slug>/`                        | none      | Activation state for a scanned tag     |
| POST   | `/api/activation/claim/`            | logged-in | Redeem a CODE-mode tag                 |
| POST   | `/api/activation/photo-claim/`      | logged-in | Redeem (or dispute) a PHOTO-mode tag   |
| GET    | `/api/activation/batches/`          | staff     | List batches                           |
| GET    | `/api/activation/batches/<pk>/`     | staff     | Batch detail + per-status stats        |

Batch generation lives in the admin (`/admin/qr_tag_activation_batches/activationbatch/generate/`), NOT in the API — printers shouldn't be able to spawn batches over HTTP.

## Quickstart

```bash
pip install djangorestframework celery Pillow
```

Add to `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    # ...
    "django.contrib.contenttypes",          # required for GenericForeignKey
    "rest_framework",
    "qr_tag_activation_batches",
]
```

Wire URLs:

```python
# config/urls.py
from django.urls import include, path
from qr_tag_activation_batches.urls import api_urlpatterns, scan_urlpatterns

urlpatterns = [
    # ...
    path("",                  include(scan_urlpatterns)),   # /q/<slug>/
    path("api/activation/",   include(api_urlpatterns)),    # API
]
```

Migrate:

```bash
python manage.py migrate
```

Wire the Celery task:

```python
# config/celery.py — beat schedule
from celery.schedules import crontab

app.conf.beat_schedule = {
    "qr-tag-confirm-provisional-claims": {
        "task": "qr_tag_activation_batches.confirm_provisional_claims",
        "schedule": crontab(minute=0),  # every hour
    },
}
```

Generate a first batch via admin:
1. Go to `/admin/qr_tag_activation_batches/activationbatch/`
2. Click "Generate batch" (custom changelist action)
3. Pick size + kind + tag_format + claim_mode
4. CSV downloads automatically with one row per (slug, code)

See [SETTINGS.md](./SETTINGS.md) for the full configuration matrix.

## Linking codes to your domain object

The `ActivationCode` model has an optional `GenericForeignKey` so you
can attach a claimed code to ANY model instance:

```python
from qr_tag_activation_batches.services import claim_code

from myapp.models import Sticker

def my_claim_view(request):
    sticker = Sticker.objects.create(owner=request.user, name="My sticker")
    claim_code(
        user=request.user,
        qr_slug=request.data["qr_slug"],
        activation_code=request.data["activation_code"],
        linked_object=sticker,   # ⬅ attaches to the freshly-created sticker
    )
```

After the call, `code.linked_object` returns the `Sticker` instance and
`sticker.activation_code_set` (or whatever reverse accessor you wire)
returns the code. If you want a stronger typed accessor, declare a
`OneToOneField(qr_tag_activation_batches.ActivationCode)` on your model
and overwrite the service usage to populate both ends.

**Why GenericFK and not a hardcoded model?** Because different projects
link to different things (Item, Sticker, Garment, AssetTag). A
`settings.ACTIVATION_TARGET_MODEL` knob would add a single layer of
indirection but force every project into the same shape. The GenericFK
keeps the template provider-agnostic; projects that only ever link to
one model can ignore the `_type` column and use a OneToOne wrapper on
their side.

## Customization hooks

| Setting                              | Purpose                                              |
|--------------------------------------|------------------------------------------------------|
| `ACTIVATION_CODE_LENGTH`             | Digits in the printed code (default 6)               |
| `ACTIVATION_BATCH_MAX_SIZE`          | Cap on one batch (default 10 000)                    |
| `QR_SLUG_LENGTH`                     | Chars in the slug encoded in the QR (default 8)      |
| `ACTIVATION_BATCH_KINDS`             | Distribution channels — list[(value, label)]         |
| `ACTIVATION_TAG_FORMATS`             | Physical tag types — list[(value, label)]            |
| `ACTIVATION_PROVISIONAL_HOURS`       | Photo-claim dispute window (default 48)              |
| `ACTIVATION_EXTRA_SLUG_GUARD`        | Optional callable to extend the uniqueness check     |
| `FRONTEND_URL`                       | Base URL injected into the exported CSV              |

## Testing

```bash
pytest apps/qr_tag_activation_batches/tests/
```

## What this does NOT include

- **A built-in `Item` (or equivalent) model.** The template stops at the
  activation code — it does NOT model the domain object that gets
  unlocked. Use the GenericFK or wire your own.
- **Image proof verification.** The PHOTO claim accepts whatever the
  user uploads. Pair with `apps.moderation` (or a perceptual-hash
  duplicate check) if you need to detect copy-paste fraud.
- **Per-tenant batch isolation.** A single admin sees all batches. Add
  a `tenant_id` column + RLS if you need multi-tenant.
- **Public batch-generation endpoint.** Only the admin can create
  batches — by design. Add a REST endpoint guarded by an API key if you
  want partner self-service.
