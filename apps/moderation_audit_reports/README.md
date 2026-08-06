# moderation-audit-reports

═════════════════════════════════════════════
Template : moderation-audit-reports
Version  : 1.0.0
Mode     : EXTRACT-A
Source   : SMN/apps/moderation
Stack    : Django 5+ / DRF / (unfold optional)
Deps     : `djangorestframework`
Used by  : (none yet)
═════════════════════════════════════════════

Generic content-report pipeline with auto-priority, ban registry, and an
append-only audit log. Pulled out of SendMeNow's moderation app and made
agnostic to your underlying content store (Postgres rows, Redis blobs,
prefix-namespaced ids — they all work).

## Why this template

- **Auto-priority that learns from repeats.** Keyword sets (FR + EN
  defaults) escalate threats / hate / minors instantly; on top of that,
  3+ open reports against the same target bump the priority one notch.
  Repeat reports are signal — one user might be wrong, three rarely are.
- **String-based ``target_id``.** Free-form, max 100 chars. Holds a bare
  UUID, a Postgres integer PK, or a prefix-namespaced id like
  ``conv_msg:<uuid>`` when one ``target_type`` covers multiple kinds.
  No polymorphic FK, no migration when you add a new content type.
- **Append-only audit log.** Every moderator action writes a
  ``ModerationLog`` row with ``before`` / ``after`` JSON snapshots. The
  admin disables add-permission so logs cannot be fabricated or back-
  dated through the UI — only ``services.log_action()`` writes.
- **Ban registry that survives expiry.** Time-limited bans
  (``banned_until``) automatically read as "not banned" once the date
  passes, even before a moderator deletes the row. ``selectors.is_banned``
  is the single source of truth.
- **Configurable target types AND keywords.** Three settings let you
  tune the template per product without forking the code.

## Models

| Model           | Purpose                                                            |
|-----------------|--------------------------------------------------------------------|
| `Report`        | One user-submitted report. Auto-prioritized at submit.             |
| `BannedUser`    | Audit-only ban record (who banned whom, when, why, until when).    |
| `ModerationLog` | Append-only trail of every moderator action with before/after.     |

## API

### Public (authenticated)

| Method | Path                                  | Purpose                |
|--------|---------------------------------------|------------------------|
| POST   | `/api/moderation/reports/`            | File a report          |

### Admin (staff only)

| Method | Path                                                  | Purpose                  |
|--------|-------------------------------------------------------|--------------------------|
| GET    | `/api/moderation/admin/reports/`                      | List the queue          |
| GET    | `/api/moderation/admin/reports/<id>/`                 | Single report detail    |
| PATCH  | `/api/moderation/admin/reports/<id>/triage/`          | Change status           |
| POST   | `/api/moderation/admin/users/<user_id>/ban/`          | Ban a user              |
| POST   | `/api/moderation/admin/users/<user_id>/unban/`        | Lift a ban              |

## Priority computation

`services.compute_priority(target_type, target_id, reason, description)`
returns an integer 0–3. Decision tree (first match wins):

```
1. URGENT  — reason in {threat, minor, self_harm}
             OR description matches MODERATION_URGENT_KEYWORDS
2. HIGH    — reason in {hate, illegal}
             OR description matches MODERATION_HIGH_KEYWORDS
3. MEDIUM  — reason in {harassment, nsfw}
4. LOW     — everything else (default for spam / other)

Escalation:
  if open_reports_for_target(...) >= MODERATION_REPEAT_REPORT_THRESHOLD - 1
      then priority += 1 (capped at URGENT)
```

The function is pure (one DB read for the escalation count, no writes),
so you can unit-test it exhaustively — see `tests/test_compute_priority.py`.

## Integration with your auth flow

The "is this user banned?" check is canonical here:

```python
from moderation_audit_reports.selectors import is_banned

class IsNotBanned(BasePermission):
    def has_permission(self, request, view):
        return not is_banned(request.user)
```

If you're building your own JWT/OAuth stack alongside this template,
see the companion **`smn-auth-jwt-oauth`** template for a ready-made
login pipeline that already calls `is_banned` on token issue and refuses
to mint tokens for banned users.

If your existing User model already has an `is_banned` boolean field,
`ban_user` / `unban_user` will flip it for you — `is_banned()` uses the
BannedUser table as the source of truth so both paths agree.

## Quickstart

```bash
pip install djangorestframework
```

Add to `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    # ...
    "rest_framework",
    "moderation_audit_reports",
]
```

Wire URLs:

```python
# config/urls.py
urlpatterns = [
    # ...
    path("api/moderation/", include("moderation_audit_reports.urls")),
]
```

Migrate:

```bash
python manage.py migrate
```

See [SETTINGS.md](./SETTINGS.md) for the full configuration matrix.

## Testing

```bash
pytest apps/moderation_audit_reports/tests/
```

## Customization hooks

- `MODERATION_TARGET_TYPES` — list[(value, label)] of supported target types
- `MODERATION_URGENT_KEYWORDS` — substrings that promote a report to URGENT
- `MODERATION_HIGH_KEYWORDS` — substrings that promote a report to HIGH
- `MODERATION_REPEAT_REPORT_THRESHOLD` — open-report count for escalation (default 3)

## What this does NOT include

- **The reported content itself.** This template tracks *reports about*
  content; the content lives wherever you put it (PG, Redis, S3, …). The
  admin "Delete content" action for Redis-backed messages is a one-liner
  on top of `services.log_action()` — see the SMN reference for an
  example, but the template stays content-agnostic on purpose.
- **Reporter rate-limiting.** A spammy reporter can file 1000 reports in
  a minute. Wrap `ReportSubmitView` in `django-ratelimit` or DRF's
  `ScopedRateThrottle` if that's a concern for your traffic shape.
- **Email notifications to moderators.** No `post_save` signal fires an
  email — add one in your project if you want admin pings. Keeping the
  template SMTP-free means it works in the absence of Resend / SES.
- **Moderation queue grouping by target.** `selectors.report_queue_grouped`
  returns the raw GROUP BY result; rendering "1 row per offending item
  with reporter_count" is a frontend / view-layer concern.
