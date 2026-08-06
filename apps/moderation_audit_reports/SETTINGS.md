# SETTINGS — moderation-audit-reports

## pip dependencies

```
djangorestframework>=3.14
```

Optional:

```
django-unfold        # if your admin uses Unfold; otherwise falls back to stock ModelAdmin
```

## INSTALLED_APPS

```python
INSTALLED_APPS = [
    # ...
    "rest_framework",
    "moderation_audit_reports",
]
```

## URLs

```python
# config/urls.py
from django.urls import path, include

urlpatterns = [
    # ...
    path("api/moderation/", include("moderation_audit_reports.urls")),
]
```

## Configurable settings (all optional)

```python
# settings.py — all four have sensible defaults; override as needed.

# Target types — what kinds of objects can be reported. List of
# (value, label) tuples. ``target_type`` field is CharField(max_length=32),
# so any short slug works. Add new types here without a migration.
MODERATION_TARGET_TYPES = [
    ("message", "Message"),
    ("post",    "Post"),
    ("comment", "Comment"),
    ("user",    "User profile"),
    ("media",   "Media"),
    # ("listing", "Marketplace listing"),  # example custom type
]

# Keyword sets used by ``compute_priority``. Substring match against
# lowercased description, so prefer stems ("harcel" matches "harceler",
# "harcèlement", "harcelé") over whole words. Defaults err on the side
# of recall (more false positives, fewer missed threats).
MODERATION_URGENT_KEYWORDS = [
    # Threats / death / violence
    "violence", "menace", "menacer", "tuer", "kill", "murder",
    "mort", "death", "stab", "shoot",
    # Self-harm / suicide
    "suicide", "self-harm", "kill myself", "se tuer",
    # Minors
    "mineur", "minor", "child", "enfant", "kid", "underage",
    "pedo", "pédo", "csam",
]

MODERATION_HIGH_KEYWORDS = [
    # Harassment / bullying
    "harcel", "harass", "bully", "intimid", "stalk", "stalker",
    # Hate / discrimination
    "racis", "racist", "homophob", "transphob", "hate", "haine",
    "antisemit", "islamophob",
    # Privacy / doxxing
    "doxx", "dox ", "personal info",
    # Sexual harassment
    "sexual harass", "harcèlement sexuel",
]

# How many OPEN reports against the same target before priority escalates
# one step. Default: 3 (one user might be wrong, three rarely are).
# Set to 0 to disable repeat escalation entirely.
MODERATION_REPEAT_REPORT_THRESHOLD = 3
```

## Env vars

None required.

## Post-install verification

```bash
python manage.py check
python manage.py migrate
python manage.py test moderation_audit_reports
# or with pytest:
pytest apps/moderation_audit_reports/tests/

# curl smoke (you'll need a valid Authorization header for these):

# Submit a report (authenticated user)
curl -s -X POST http://127.0.0.1:8000/api/moderation/reports/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"target_type":"message","target_id":"abc-123","reason":"harassment","description":"keeps DMing me"}'

# List queue (staff)
curl -s http://127.0.0.1:8000/api/moderation/admin/reports/ \
  -H "Authorization: Bearer $STAFF_TOKEN"

# Triage to actioned
curl -s -X PATCH http://127.0.0.1:8000/api/moderation/admin/reports/1/triage/ \
  -H "Authorization: Bearer $STAFF_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status":"actioned","note":"confirmed"}'

# Ban a user (permanent)
curl -s -X POST http://127.0.0.1:8000/api/moderation/admin/users/42/ban/ \
  -H "Authorization: Bearer $STAFF_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"reason":"repeated harassment"}'

# Ban for 7 days
curl -s -X POST http://127.0.0.1:8000/api/moderation/admin/users/42/ban/ \
  -H "Authorization: Bearer $STAFF_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"reason":"first warning","days":7}'
```

## Companion templates

- `smn-auth-jwt-oauth` — login pipeline that calls `selectors.is_banned`
  on token issue and refuses to mint tokens for banned users. Pair the
  two for a complete "report → triage → ban → no-login" flow.
