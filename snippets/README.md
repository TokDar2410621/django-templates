# Snippets — micro-templates

Small, single-file utilities you copy-paste into a new Django project.
Unlike full templates under `apps/`, these aren't Django apps — they're
configuration helpers, middleware, exception handlers, etc. that live
next to your `settings.py` or in a utility module.

Each file is self-contained with a header docstring explaining what it
does, the env vars it needs, and where to wire it.

| Snippet | What it does | Source |
|---|---|---|
| [`storage_s3_autoswitch.py`](./storage_s3_autoswitch.py) | Auto-switch STORAGES between FileSystem and S3 based on AWS env vars. Two-namespace S3 (default = signed URLs, public = unsigned). | SMN + FIN |
| [`stripe_mode_toggle.py`](./stripe_mode_toggle.py) | Resolve `STRIPE_*` keys from `STRIPE_*_TEST` vs `STRIPE_*_LIVE` based on a single `STRIPE_MODE` env var. | SMN + FIN |
| [`redis_dual_db.py`](./redis_dual_db.py) | Two-DB Redis pattern (ephemeral vs cache/broker/channel-layer), with configurable DB numbers via env. | SMN + FIN |
| [`channels_jwt_middleware.py`](./channels_jwt_middleware.py) | Django Channels middleware that authenticates WebSocket connections via JWT in the `?token=` query param. | FIN |
| [`pem_env_loader.py`](./pem_env_loader.py) | Load PEM keys (Apple `.p8`, VAPID private) from either filesystem path or inline `\n`-escaped env var. Survives Railway env-var input. | FIN |
| [`drf_ratelimit_429.py`](./drf_ratelimit_429.py) | Custom DRF EXCEPTION_HANDLER that maps `django_ratelimit.Ratelimited` → HTTP 429 (instead of the default 403). | FIN |

## How to use

1. Copy the snippet file into your project (typically next to `settings.py`
   or under `apps/<utility_app>/`).
2. Read the top-of-file docstring for the exact wire-up snippet.
3. Adjust the `config` callable if you don't use `python-decouple` (the
   snippets accept any `(key, default=) -> str` callable, including
   `django-environ` and plain `os.environ.get`).

## Why snippets and not apps?

Each of these is < 100 lines, doesn't have models or views, and lives in
the project's settings/middleware layer — not in an installable Django
app. Wrapping them in an app would add ceremony (apps.py, AppConfig,
INSTALLED_APPS entry) for zero benefit.
