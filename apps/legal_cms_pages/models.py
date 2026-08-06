"""Versioned legal documents — admin-editable, per-language, audit-safe.

One (kind, language) pair may have many ``LegalDocument`` rows but only ONE
active at a time (enforced by a partial unique constraint). Publishing a new
version atomically flips ``is_active`` from the old row to the new via
``services.publish_document`` — never edit ``is_active`` directly in a save().

Why versioning? Legal needs to prove "user X accepted version Y on date Z"
if a dispute arises. We never delete old versions; they stay indexed by
``effective_from`` for audit lookups.

Body is stored as Markdown — easier to write in the admin and easier to diff
between versions. Rendered to HTML at API time via ``services.render_html``
(markdown + bleach sanitization).
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


# ---------------------------------------------------------------------------
# Configurable choices
#
# Override in your project's settings:
#
#   LEGAL_DOCUMENT_KINDS = [
#       ("privacy_policy",   "Politique de confidentialité"),
#       ("terms_of_service", "Conditions d'utilisation"),
#       ("cookies_policy",   "Politique des cookies"),
#       ("custom_kind",      "Mon document custom"),
#   ]
#   LEGAL_DOCUMENT_LANGUAGES = [
#       ("fr", "Français"),
#       ("en", "English"),
#   ]
#   LEGAL_DEFAULT_LANGUAGE = "fr"
#
# Defaults below cover the most common case.
# ---------------------------------------------------------------------------
DEFAULT_KINDS: list[tuple[str, str]] = [
    ("privacy_policy",   "Politique de confidentialité"),
    ("terms_of_service", "Conditions d'utilisation"),
    ("cookies_policy",   "Politique des cookies"),
]
DEFAULT_LANGUAGES: list[tuple[str, str]] = [
    ("fr", "Français"),
    ("en", "English"),
]


def _kinds() -> list[tuple[str, str]]:
    return list(getattr(settings, "LEGAL_DOCUMENT_KINDS", DEFAULT_KINDS))


def _languages() -> list[tuple[str, str]]:
    return list(getattr(settings, "LEGAL_DOCUMENT_LANGUAGES", DEFAULT_LANGUAGES))


def _default_language() -> str:
    return getattr(settings, "LEGAL_DEFAULT_LANGUAGE", "fr")


class LegalDocument(models.Model):
    """One published version of a legal document, in one language."""

    kind = models.CharField(
        max_length=48,
        choices=_kinds(),
        db_index=True,
    )
    language = models.CharField(
        max_length=8,
        choices=_languages(),
        default=_default_language(),
        db_index=True,
    )

    title = models.CharField(
        max_length=200,
        help_text="Titre affiché en haut de la page.",
    )
    body_markdown = models.TextField(
        help_text=(
            "Contenu Markdown. Liens, listes, titres ## et **gras** "
            "supportés. Le HTML est généré automatiquement à la lecture."
        ),
    )

    effective_from = models.DateTimeField(
        help_text="Date d'entrée en vigueur officielle de cette version.",
    )

    is_active = models.BooleanField(default=False, db_index=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="legal_documents_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "legal_document"
        ordering = ("kind", "language", "-effective_from")
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "language"],
                condition=models.Q(is_active=True),
                name="legal_unique_active_per_kind_lang",
            ),
        ]
        indexes = [
            models.Index(fields=["kind", "language", "is_active"]),
        ]

    def __str__(self) -> str:
        status = "ACTIVE" if self.is_active else "archived"
        return f"{self.get_kind_display()} [{self.language}] ({status})"
