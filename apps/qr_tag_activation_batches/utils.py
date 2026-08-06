"""QR slug + activation code generators.

QR slug: lowercase alphanumeric (``QR_SLUG_LENGTH`` chars, default 8).
~2.8 trillion possibilities at length 8. Used as the path segment of the
public scan URL (``/q/<slug>/``). Uniqueness is enforced at the DB level on
``ActivationCode.qr_slug`` (and, if the caller links to its own domain
model, ideally on that model's slug column as well).

Activation code: digits only (``ACTIVATION_CODE_LENGTH`` chars, default 6).
Stored as a string field — no leading-zero suppression. Generated when an
``ActivationBatch`` is created and printed on the carton / scratch-off.
Uniqueness is enforced per-batch, not globally — the (batch, code) pair
is the proof, not the code alone.
"""
from __future__ import annotations

import secrets
import string

from django.conf import settings


_QR_ALPHABET = string.ascii_lowercase + string.digits
_DIGIT_ALPHABET = string.digits


def _qr_slug_length() -> int:
    return int(getattr(settings, "QR_SLUG_LENGTH", 8))


def _activation_code_length() -> int:
    return int(getattr(settings, "ACTIVATION_CODE_LENGTH", 6))


def generate_qr_slug(length: int | None = None) -> str:
    """Random N-char lowercase alphanumeric. Uniqueness is the caller's job."""
    n = length if length is not None else _qr_slug_length()
    return "".join(secrets.choice(_QR_ALPHABET) for _ in range(n))


def generate_activation_code(length: int | None = None) -> str:
    """Random N-digit code. Uniqueness is the caller's job."""
    n = length if length is not None else _activation_code_length()
    return "".join(secrets.choice(_DIGIT_ALPHABET) for _ in range(n))
