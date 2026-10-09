# Django Templates Library

Personal library of reusable Django apps. Each `apps/<slug>/` is an autonomous
Django app you copy into a new project and wire up via `INSTALLED_APPS` +
URLs. Every template depends on `settings.AUTH_USER_MODEL` (never imports
`User` directly) and ships with `models / views / serializers / services /
selectors / urls / admin / tests` separated.

## Layout

```
django-templates/
  README.md       (this file)
  CATALOG.md      (detailed technical index)
  apps/
    <slug>/
      apps.py
      models.py
      services.py
      selectors.py
      serializers.py
      views.py
      urls.py
      admin.py
      tasks.py            (if Celery)
      signals.py          (if needed)
      migrations/0001_initial.py
      tests/
      README.md           (integration guide)
      SETTINGS.md         (env vars + INSTALLED_APPS to add)
      examples/           (minimal standalone proof)
  snippets/
    <name>.py             (micro-templates: middleware, helpers, settings mixins)
```

## Using it with Claude Code

Install the skill in `skill/django-templates-library/` (see `skill/README.md`).
Before any Django backend task, Claude syncs this library (clone if missing,
update if behind), reads `CATALOG.md` and picks the right template.

## How to use a template

1. Copy `apps/<slug>/` into your project under `apps/`.
2. Read `apps/<slug>/SETTINGS.md` — install pip deps, add to `INSTALLED_APPS`,
   set env vars.
3. Wire URLs in `config/urls.py` per the template's `urls.py`.
4. Run `python manage.py migrate`.
5. Run the template's tests with `pytest apps/<slug>/tests/`.

## Production-ready criteria (non-negotiable for every template)

- Type hints on public functions
- pytest tests passing (happy path + 2 negatives min)
- Single clean initial migration
- Django admin (ModelAdmin per model, `search_fields`, `list_filter`)
- Explicit error handling (never `except: pass`)
- Structured logging via `logging.getLogger`
- Docstrings on public methods + classes
- Layered: `services.py` (business logic), `selectors.py` (queries), `views.py`
  (HTTP only)
- Validation at the right level (serializer = shape, service = rules)
- Settings configurable via `django.conf.settings`
- Depends on `settings.AUTH_USER_MODEL`

## License

MIT. Use it, copy it, ship it. A link back is appreciated, never required.
