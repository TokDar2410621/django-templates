"""Legal document services — publish + render."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import bleach
import markdown as md
from django.db import transaction

from .models import LegalDocument, _default_language

logger = logging.getLogger(__name__)


# Allowed HTML after Markdown rendering. Bleach scrubs everything else so a
# careless paste of raw <script> in the markdown body never reaches the API.
_ALLOWED_TAGS: set[str] = {
    "p", "br", "hr",
    "a", "strong", "em", "u", "s", "code", "pre",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li",
    "blockquote",
    "table", "thead", "tbody", "tr", "th", "td",
}
_ALLOWED_ATTRS: dict[str, list[str]] = {
    "a": ["href", "title", "rel", "target"],
    "th": ["align"],
    "td": ["align"],
}


def render_html(body_markdown: str) -> str:
    """Convert markdown source → sanitized HTML."""
    raw = md.markdown(
        body_markdown or "",
        extensions=["extra", "sane_lists", "tables"],
        output_format="html",
    )
    return bleach.clean(
        raw,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        strip=True,
    )


def get_active(kind: str, language: Optional[str] = None) -> Optional[LegalDocument]:
    """Return the currently active document for (kind, language).

    Falls back to the project's ``LEGAL_DEFAULT_LANGUAGE`` if the requested
    language has no active version — better to show SOMETHING legally binding
    than a 404.
    """
    fallback = _default_language()
    lang = language or fallback
    qs = LegalDocument.objects.filter(kind=kind, is_active=True)
    doc = qs.filter(language=lang).first()
    if doc is None and lang != fallback:
        doc = qs.filter(language=fallback).first()
    return doc


@transaction.atomic
def publish_document(
    *,
    kind: str,
    language: str,
    title: str,
    body_markdown: str,
    effective_from: datetime,
    created_by=None,
) -> LegalDocument:
    """Create a new active version atomically.

    Deactivates any existing active row for (kind, language) first, then
    inserts the new active row — both in the same transaction so the partial
    unique constraint can never race.
    """
    LegalDocument.objects.filter(
        kind=kind, language=language, is_active=True,
    ).update(is_active=False)
    doc = LegalDocument.objects.create(
        kind=kind,
        language=language,
        title=title,
        body_markdown=body_markdown,
        effective_from=effective_from,
        is_active=True,
        created_by=created_by,
    )
    logger.info(
        "legal.published kind=%s language=%s id=%s by=%s",
        kind, language, doc.pk, getattr(created_by, "pk", None),
    )
    return doc
