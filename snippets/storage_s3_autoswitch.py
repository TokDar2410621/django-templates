"""Auto-switch storage between local FileSystem and S3 at boot.

Drop this into your `config/settings/base.py` (or wherever your STORAGES
dict lives). It flips to S3 when both AWS_ACCESS_KEY_ID and
AWS_STORAGE_BUCKET_NAME are set; otherwise falls back to FileSystem.

Two-namespace S3 setup:
  - "default"  → uploads served with signed URLs (private, 24h expiry)
  - "public"   → uploads served without auth (avatars, public assets)

Use `default` for user-uploaded private content, `public` for things you
want directly cacheable by a CDN.

USAGE — copy this whole file into a `storage.py` next to your settings,
then in `base.py`:

    from .storage import build_storages
    STORAGES = build_storages(config=config)

`config` here is `decouple.config` — adapt the calls if you use
django-environ or plain os.environ.

DEPENDS ON — `django-storages[s3]>=1.14`, `whitenoise>=6.0`, optionally
`boto3` (transitive dep of django-storages).
"""
from __future__ import annotations

from typing import Any, Callable


def build_storages(*, config: Callable[..., Any]) -> dict[str, Any]:
    """Return a Django STORAGES dict with auto S3 vs FileSystem.

    Pass `config` = python-decouple's `config` callable (or any helper
    that takes a key + `default=` kwarg).
    """
    access_key = config("AWS_ACCESS_KEY_ID", default="")
    bucket = config("AWS_STORAGE_BUCKET_NAME", default="")
    use_s3 = bool(access_key and bucket)

    if not use_s3:
        return {
            "default": {
                "BACKEND": "django.core.files.storage.FileSystemStorage",
            },
            "staticfiles": {
                "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
            },
        }

    common = {
        "bucket_name": bucket,
        "region_name": config("AWS_S3_REGION_NAME", default="us-east-1"),
        "file_overwrite": False,
    }
    return {
        # Private uploads — signed URLs, 24h expiry
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                **common,
                "querystring_auth": True,
                "querystring_expire": 24 * 3600,
            },
        },
        # Public assets — no auth (avatars, og-images, etc.)
        "public": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                **common,
                "querystring_auth": False,
            },
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }


def is_s3_active(*, config: Callable[..., Any]) -> bool:
    """Mirror of the flip — useful when you need to gate code that depends
    on S3 features (e.g. presigned uploads) without re-checking env vars
    in two places."""
    return bool(
        config("AWS_ACCESS_KEY_ID", default="")
        and config("AWS_STORAGE_BUCKET_NAME", default="")
    )
