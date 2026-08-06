# -*- coding: utf-8 -*-
"""Hermetic fixtures: a minimal in-memory Redis covering exactly the surface
store.py uses. No fakeredis dependency, no network."""
from __future__ import annotations

import fnmatch
import time

import pytest

from realtime_messaging import store


class FauxPipeline:
    def __init__(self, client):
        self.client = client
        self.ops = []

    def __getattr__(self, name):
        def enregistre(*args, **kwargs):
            self.ops.append((name, args, kwargs))
            return self

        return enregistre

    def execute(self):
        for name, args, kwargs in self.ops:
            getattr(self.client, name)(*args, **kwargs)
        self.ops = []


class FauxRedis:
    """Le sous-ensemble de redis.Redis(decode_responses=True) que store.py touche."""

    def __init__(self):
        self.h: dict[str, dict] = {}
        self.kv: dict[str, str] = {}
        self.sets: dict[str, set] = {}
        self.z: dict[str, dict] = {}
        self.expiries: dict[str, float] = {}

    # hashes
    def hset(self, key, field=None, value=None, mapping=None):
        d = self.h.setdefault(key, {})
        if mapping:
            d.update({k: str(v) for k, v in mapping.items()})
        if field is not None:
            d[field] = str(value)

    def hgetall(self, key):
        return dict(self.h.get(key, {})) if not self._expire_morte(key) else {}

    def hget(self, key, field):
        if self._expire_morte(key):
            return None
        return self.h.get(key, {}).get(field)

    # strings / sets / zsets
    def set(self, key, value):
        self.kv[key] = str(value)

    def get(self, key):
        return self.kv.get(key)

    def sadd(self, key, *values):
        self.sets.setdefault(key, set()).update(str(v) for v in values)

    def smembers(self, key):
        return set(self.sets.get(key, set()))

    def zadd(self, key, mapping):
        self.z.setdefault(key, {}).update(mapping)

    def zrange(self, key, start, end):
        items = sorted(self.z.get(key, {}).items(), key=lambda kv: kv[1])
        end = None if end == -1 else end + 1
        return [k for k, _ in items[start:end]]

    def zrevrange(self, key, start, end):
        return list(reversed(self.zrange(key, 0, -1)))[start : None if end == -1 else end + 1]

    def zrem(self, key, member):
        self.z.get(key, {}).pop(member, None)

    # ttl
    def expire(self, key, seconds):
        self.expiries[key] = time.time() + seconds

    def ttl(self, key):
        if key not in self.expiries:
            return -1 if (key in self.h or key in self.kv) else -2
        return max(int(self.expiries[key] - time.time()), 0) or -2

    def exists(self, key):
        return int((key in self.h or key in self.kv) and not self._expire_morte(key))

    def delete(self, *keys):
        for key in keys:
            self.h.pop(key, None)
            self.kv.pop(key, None)
            self.expiries.pop(key, None)

    def scan_iter(self, match="*"):
        for key in list(self.h) + list(self.kv):
            if fnmatch.fnmatch(key, match):
                yield key

    def pipeline(self):
        return FauxPipeline(self)

    def _expire_morte(self, key):
        exp = self.expiries.get(key)
        return exp is not None and exp <= time.time()


@pytest.fixture()
def faux_redis(settings):
    settings.REALTIME_MESSAGING_REDIS_URL = "redis://faux:6379/0"
    client = FauxRedis()
    store.set_client_for_tests(client)
    yield client
    store.set_client_for_tests(None)
