# hashed-api-tokens

═════════════════════════════════════════════
Template : hashed-api-tokens
Version  : 1.0.0
Mode     : EXTRACT-A
Source   : blog-dashboard/sites_mgmt (ApiToken + ApiTokenAuthentication)
Stack    : Django 5+ / DRF / (unfold optional)
Deps     : `djangorestframework>=3.14`
Used by  : (none yet)
═════════════════════════════════════════════

Per-user, long-lived API tokens for machine-to-machine access. The plain
token is shown ONCE at creation and never persisted — only its SHA256 hash
is stored in the database.

## Why this template

- **Hash-only storage.** If your DB is ever dumped, no token is recoverable.
  We persist `SHA256(plain)` and nothing else.
- **Two header conventions out of the box.** `Authorization: Bearer <token>`
  AND `X-Api-Key: <token>` both work, because half the integration platforms
  on the market only let you set custom headers (`X-Api-Key`) while the
  other half assume `Authorization`.
- **Recognizable in the UI without leaking.** A short `key_prefix` (first
  12 chars) is stored separately so admins/users can identify a token in a
  list (`tkn_aB7cD9eF…`) without having anything attacker-useful.
- **Soft revocation with audit trail.** `revoked_at` timestamps WHEN a token
  was disabled. No hard deletes.
- **Rate-limited `last_used_at` writes.** Even a high-QPS integration only
  triggers one UPDATE per minute per token — no DB hot spot.
- **Configurable token prefix** via the `API_TOKEN_PREFIX` setting (default
  `"tkn"`).

## Security notes

- **Plain tokens are never persisted.** The only place the plain value
  appears is in the response body of `POST /api/tokens/`. After that, it
  exists only on whatever client the user pasted it into.
- **The admin shows the hash, not the plain token.** This is deliberate:
  the plain token does not exist anywhere in the DB to begin with, so the
  admin can't show it even if a maintainer adds the field.
- **Revocation is soft.** Tokens stay in the table (with `revoked_at` set)
  for audit purposes. Set up a periodic job to hard-delete rows where
  `revoked_at < now - 90 days` if your compliance posture requires it.
- **Why SHA256 and not bcrypt/argon2?** The plain token is already 32 bytes
  of cryptographic randomness from `secrets.token_urlsafe`. A slow hash
  buys nothing against high-entropy input — there's no useful pre-image
  attack surface. SHA256 is also indexable (O(1) lookup); bcrypt would
  force a full table scan on every authenticated request.
- **Constant-time-ish lookup.** We hash the incoming token and look up by
  the unique hash. We never compare plain values, and the same generic
  "Invalid or revoked token." error is returned for both unknown and
  revoked tokens so a probing attacker can't distinguish.

## API

| Method | Path                                | Auth          | Purpose                                  |
|--------|-------------------------------------|---------------|------------------------------------------|
| GET    | `/api/tokens/`                      | session/JWT   | List requester's active tokens           |
| GET    | `/api/tokens/?include_revoked=1`    | session/JWT   | List incl. revoked (audit view)          |
| POST   | `/api/tokens/`                      | session/JWT   | Create token, returns plain value ONCE   |
| POST   | `/api/tokens/<id>/revoke/`          | session/JWT   | Soft-revoke a token (idempotent)         |

`POST /api/tokens/` request body:

```json
{ "name": "n8n production" }
```

Response (only place the plain token appears):

```json
{
  "id": 7,
  "name": "n8n production",
  "key_prefix": "tkn_aB7cD9eF",
  "created_at": "2026-05-22T10:30:00Z",
  "token": "tkn_aB7cD9eF_…_43-char-suffix",
  "message": "Store this token somewhere safe — it will never be displayed again."
}
```

Subsequent `GET /api/tokens/` calls return everything EXCEPT the plain
`token` field — that one is unrecoverable by design.

## Quickstart

```bash
pip install djangorestframework
```

Add to `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    # ...
    "rest_framework",
    "hashed_api_tokens",
]
```

Wire URLs:

```python
# config/urls.py
urlpatterns = [
    # ...
    path("api/tokens/", include("hashed_api_tokens.urls")),
]
```

Migrate:

```bash
python manage.py migrate hashed_api_tokens
```

Done. Users can now create tokens via `POST /api/tokens/`.

## Integrating the authentication backend

To protect ONE specific view:

```python
# yourapp/views.py
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from hashed_api_tokens.authentication import HashedTokenAuthentication

class MyMachineEndpoint(APIView):
    authentication_classes = [HashedTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # request.user      → token owner
        # request.auth      → ApiToken instance (use .name for audit logs)
        return Response({"ok": True})
```

To enable it globally (typically alongside JWT/session for the dashboard):

```python
# settings.py
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "hashed_api_tokens.authentication.HashedTokenAuthentication",
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
}
```

The backend returns `None` (rather than failing) when no token header is
present, so it stacks cleanly with other backends.

To require an ACTIVE token (block requests that authenticated via session
or JWT from hitting machine-only endpoints):

```python
from hashed_api_tokens.permissions import HasActiveApiToken

class MachineOnly(APIView):
    permission_classes = [HasActiveApiToken]
```

## Customization hooks

- `API_TOKEN_PREFIX` — string prefix on every plain token. Default `"tkn"`.
  Change to your product code (`"smn"`, `"fin"`, `"btb"`) for easy
  identification in logs and configs.

See [SETTINGS.md](./SETTINGS.md) for the full configuration matrix.

## Testing

```bash
pytest apps/hashed_api_tokens/tests/
```

Test suite covers:

- Plain token returned exactly once on create
- Hash matches `SHA256(plain)` and plain never appears in any DB column
- `Authorization: Bearer` AND `X-Api-Key` headers both authenticate
- Revoked tokens return 401
- Unknown tokens return 401 (same error as revoked — no leakage)
- Garbage-format tokens are rejected
- `last_used_at` updates are rate-limited to once per minute
- Owner can revoke own tokens; staff can revoke any; other users cannot
- Revocation is idempotent
- `GET /api/tokens/` excludes revoked by default; `?include_revoked=1`
  flips it on for audit views

## What this does NOT include

- **Scoping.** Tokens grant whatever access the owning user has — no
  per-token permission narrowing (`read_only`, `posts_only`, …). Add a
  JSON `scopes` field and check it in views if you need this.
- **Expiry.** Tokens are long-lived until revoked. Add a `expires_at`
  field + a Celery cleanup task if you want time-bound tokens.
- **Rate limiting per token.** Use DRF's `UserRateThrottle` or a plan-aware
  throttle (see blog-dashboard `api_v1.ApiPlanThrottle` for an example) on
  top of this template; the template itself does not throttle.
- **Audit log of token usage.** We update `last_used_at` and emit an
  `INFO` log on create/revoke, but we don't record per-request usage.
  Wire a middleware or DRF logging if you need it.
- **Frontend UI.** This template ships the API only. Build whatever screen
  fits your product — typically: list with name+prefix+last_used_at, a
  "Create" button that displays the plain token in a one-time modal, a
  trash icon that POSTs to `/revoke/`.
