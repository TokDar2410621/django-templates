"""Per-channel backends.

Each backend is responsible for ONE provider integration and exposes a
single ``send(...)`` callable. Backends never raise on missing creds or
provider errors — they return a ``SendResult`` so the service layer can
decide what to do (log, retry, fall back to another channel, etc.).
"""
from .base import SendResult, NotificationBackend  # noqa: F401
