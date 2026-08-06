"""Read-only queries for legal documents."""
from __future__ import annotations

from typing import Iterable

from .models import LegalDocument, _default_language


def list_active_for_language(language: str) -> list[LegalDocument]:
    """All active documents in a given language.

    For kinds with no active version in the requested language, falls back to
    the project's default-language version so a frontend footer that links
    to every kind always resolves to SOMETHING.
    """
    fallback = _default_language()
    active = list(
        LegalDocument.objects
        .filter(is_active=True, language=language)
        .order_by("kind")
    )
    if language != fallback:
        covered = {doc.kind for doc in active}
        fb = LegalDocument.objects.filter(
            is_active=True, language=fallback,
        ).exclude(kind__in=covered).order_by("kind")
        active.extend(fb)
    return active


def versions_for_kind(kind: str, language: str) -> Iterable[LegalDocument]:
    """All versions (active + archived) of one document. Audit-friendly."""
    return (
        LegalDocument.objects
        .filter(kind=kind, language=language)
        .order_by("-effective_from")
    )
