# legal-cms-pages

═════════════════════════════════════════════
Template : legal-cms-pages
Version  : 1.0.0
Mode     : EXTRACT-A
Source   : FIN/apps/legal
Stack    : Django 5+ / DRF / markdown / bleach / (unfold optional)
Deps     : `markdown>=3.5`, `bleach>=6.0`, `djangorestframework`
Used by  : (none yet)
═════════════════════════════════════════════

Versioned legal documents (Privacy Policy, ToS, Cookies, etc.) editable from
the admin, served via a public read API with Markdown→sanitized-HTML rendering.

## Why this template

- **Versioning that holds up in court.** Old versions are never deleted; a
  partial unique constraint guarantees exactly one active row per (kind,
  language).
- **Atomic publishing.** `services.publish_document` deactivates the
  previous active row and inserts the new one in a single transaction.
- **Markdown body + Bleach sanitization.** Operators write Markdown in a
  plain textarea (easy to diff across versions); HTML is rendered + scrubbed
  on the API side, so even a careless paste of `<script>` is safe.
- **Language fallback.** Requests for an unpublished language fall back to
  `LEGAL_DEFAULT_LANGUAGE` so the footer link always resolves.
- **Configurable kinds.** Add `parental_consent`, `dpa`, custom document
  types via `LEGAL_DOCUMENT_KINDS` in settings — no code change.

## API

| Method | Path                                | Auth | Purpose                                |
|--------|-------------------------------------|------|----------------------------------------|
| GET    | `/api/legal/?lang=fr`               | none | Index — all kinds with active versions |
| GET    | `/api/legal/<kind>/?lang=fr`        | none | Full doc with `body_html` + `body_markdown` |

## Quickstart

```bash
pip install markdown bleach djangorestframework
```

Add to `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    # ...
    "legal_cms_pages",
]
```

Wire URLs:

```python
# config/urls.py
urlpatterns = [
    # ...
    path("api/legal/", include("legal_cms_pages.urls")),
]
```

Migrate:

```bash
python manage.py migrate
```

Create the first document via admin (`/admin/legal_cms_pages/legaldocument/`):
1. Add → fill kind + language + title + Markdown body + effective_from
2. Save as draft (`is_active=False`)
3. Select the row → Action: "Publish this version"

See [SETTINGS.md](./SETTINGS.md) for the full configuration matrix.

## Testing

```bash
pytest apps/legal_cms_pages/tests/
```

## Customization hooks

- `LEGAL_DOCUMENT_KINDS` — list[(value, label)] of supported document kinds
- `LEGAL_DOCUMENT_LANGUAGES` — list[(code, label)] of supported languages
- `LEGAL_DEFAULT_LANGUAGE` — fallback language code (default `"fr"`)

## What this does NOT include

- User acceptance tracking (which user accepted which version when). If you
  need this, add a `LegalAcceptance(user, document, accepted_at)` table on
  top — out of scope for this template because the modeling depends on
  whether you want per-version or per-kind acceptance, and whether you store
  IP/user-agent for proof.
- Rich-text editor in the admin. The plain textarea + Markdown is a
  deliberate choice (easier diffs, no widget dependency).
