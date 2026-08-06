"""Redis dual-DB setup — ephemeral data vs cache/broker/channel-layer.

Two logical Redis DBs, deliberately separated so an aggressive cache
flush never wipes ephemeral data with TTLs, and so different retention
policies can be applied per DB:

  - EPHEMERAL_DB → user data with TTLs (chat messages, sessions,
                   short-lived state). Backed up if Redis backs up at all.
  - CACHE_DB     → Django cache + Celery broker/result + channel layer
                   + rate-limit counters. Safe to FLUSHDB on demand.

DB numbers are configurable via env so multiple Django projects sharing
the same Redis instance can stay isolated. Defaults here pick (0, 1);
projects that coexist with another (like SMN ↔ FIN sharing dev Redis)
should override e.g. to (3, 4) to avoid stomping.

USAGE — copy this file next to settings, then in `base.py`:

    from .redis_dual import build_redis_config
    REDIS = build_redis_config(config=config)

    REDIS_EPHEMERAL_URL = REDIS["ephemeral_url"]   # raw URL for direct redis-py
    REDIS_CACHE_URL = REDIS["cache_url"]

    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": REDIS["cache_url"],
            "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
        }
    }

    CELERY_BROKER_URL = REDIS["cache_url"]
    CELERY_RESULT_BACKEND = REDIS["cache_url"]

    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [REDIS["cache_url"]]},
        }
    }

DEPENDS ON — `django-redis>=5.4`, `channels-redis>=4.0` (if using
Channels), `celery[redis]>=5.3` (if using Celery).
"""
from __future__ import annotations

from typing import Any, Callable


def build_redis_config(
    *,
    config: Callable[..., Any],
    default_ephemeral_db: str = "0",
    default_cache_db: str = "1",
) -> dict[str, str]:
    """Return Redis URLs + DB numbers, configurable via env.

    Env vars (all optional):
        REDIS_URL              → e.g. redis://default:pass@host:6379
        REDIS_EPHEMERAL_DB     → DB number (default = default_ephemeral_db)
        REDIS_CACHE_DB         → DB number (default = default_cache_db)
    """
    redis_url = config("REDIS_URL", default="redis://localhost:6379")
    ephemeral_db = config("REDIS_EPHEMERAL_DB", default=default_ephemeral_db)
    cache_db = config("REDIS_CACHE_DB", default=default_cache_db)
    return {
        "base_url": redis_url,
        "ephemeral_db": ephemeral_db,
        "cache_db": cache_db,
        "ephemeral_url": f"{redis_url}/{ephemeral_db}",
        "cache_url": f"{redis_url}/{cache_db}",
    }
