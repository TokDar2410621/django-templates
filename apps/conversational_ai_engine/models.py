"""Domain models for the conversational AI engine.

Three models:

* :class:`PersonaContext` — 1-to-1 with the project's user. Stores the
  metadata that will be injected at the top of every prompt
  (role, industry, audience, writing style, examples, free-form context).
* :class:`PromptTemplate` — user-owned prefix/suffix wrappers that surround
  the raw input before it is sent to the LLM.
* :class:`Generation` — audit record of every call: input, output, tone,
  token counts, USD cost, optional retrieved-memory ids (RAG hook).

Design notes
------------

* We use ``settings.AUTH_USER_MODEL`` everywhere — never import ``User``
  directly. Templates have to work on projects with custom user models.
* The ``session_key`` field on :class:`Generation` exists so anonymous
  trials (no auth) can still be persisted and rate-limited via Django's
  session framework. Either ``user`` OR ``session_key`` must be set
  (enforced at the DB level by a check constraint).
* The choice list for ``tone`` is read at runtime from
  ``settings.AI_TONES`` so projects can override without a migration.
* ``Generation.metadata`` is a JSONField holding free-form provider
  metadata (model name, stop_reason, cache hit info, etc.). The schema is
  intentionally not formalised — provider implementations choose what to
  drop in there.
"""
from __future__ import annotations

from typing import Iterable

from django.conf import settings
from django.db import models


# ---------------------------------------------------------------------------
# Tones — override in your project with:
#
#   AI_TONES = [
#       ("professionnel", "Professionnel"),
#       ("inspirant",     "Inspirant"),
#       ("storytelling",  "Storytelling"),
#       ("educatif",      "Éducatif"),
#       ("humoristique",  "Humoristique"),
#       ("technique",     "Technique"),       # example custom tone
#   ]
#
# Code stored is short, label is operator-facing.
# ---------------------------------------------------------------------------
DEFAULT_TONES: list[tuple[str, str]] = [
    ("professionnel", "Professionnel"),
    ("inspirant",     "Inspirant"),
    ("storytelling",  "Storytelling"),
    ("educatif",      "Éducatif"),
    ("humoristique",  "Humoristique"),
]


def _tones() -> list[tuple[str, str]]:
    return list(getattr(settings, "AI_TONES", DEFAULT_TONES))


def _default_tone() -> str:
    return _tones()[0][0] if _tones() else "professionnel"


# ---------------------------------------------------------------------------
# Persona — author context injected into every prompt.
# ---------------------------------------------------------------------------
class PersonaContext(models.Model):
    """Per-user persona used to flavour generations.

    All fields are optional. ``build_prompt_context()`` produces a single
    string that the service layer prepends to the system prompt when the
    user has at least one filled field.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ai_persona",
    )
    role = models.CharField(
        max_length=200, blank=True,
        help_text="Job title or function (e.g. 'Senior Backend Engineer').",
    )
    industry = models.CharField(
        max_length=200, blank=True,
        help_text="Industry / sector (e.g. 'FinTech, B2B SaaS').",
    )
    expertise = models.TextField(
        blank=True,
        help_text="Areas of expertise the AI should lean on.",
    )
    target_audience = models.TextField(
        blank=True,
        help_text="Who the generated content speaks to.",
    )
    writing_style = models.TextField(
        blank=True,
        help_text="Tone, vocabulary, voice traits (e.g. 'direct, concrete, "
                  "first-person, French').",
    )
    bio = models.TextField(
        blank=True,
        help_text="Short bio / description of the author.",
    )
    examples = models.TextField(
        blank=True,
        help_text="Example outputs the user likes — guides the model's voice.",
    )
    additional_context = models.TextField(
        blank=True,
        help_text="Any other free-form context. Appended verbatim.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ai_persona_context"
        verbose_name = "Persona context"
        verbose_name_plural = "Persona contexts"

    def __str__(self) -> str:
        return f"PersonaContext(user_id={self.user_id})"

    @property
    def has_context(self) -> bool:
        return any([
            self.role, self.industry, self.expertise,
            self.target_audience, self.writing_style, self.bio,
            self.examples, self.additional_context,
        ])

    def build_prompt_context(self) -> str:
        """Return the multi-line context string injected into the system prompt.

        Empty string when no field is filled — caller can simply check the
        return value and skip injection.
        """
        if not self.has_context:
            return ""
        parts: list[str] = ["AUTHOR CONTEXT:"]
        if self.role:
            parts.append(f"- Role: {self.role}")
        if self.industry:
            parts.append(f"- Industry: {self.industry}")
        if self.expertise:
            parts.append(f"- Expertise: {self.expertise}")
        if self.target_audience:
            parts.append(f"- Target audience: {self.target_audience}")
        if self.writing_style:
            parts.append(f"- Writing style: {self.writing_style}")
        if self.bio:
            parts.append(f"- Bio: {self.bio}")
        if self.examples:
            parts.append(f"\nEXAMPLES THE AUTHOR LIKES:\n{self.examples}")
        if self.additional_context:
            parts.append(f"\nADDITIONAL CONTEXT:\n{self.additional_context}")
        parts.append(
            "\nAdapt your output to this profile. Use vocabulary and examples "
            "that are consistent with the author's industry and audience."
        )
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Prompt template — prefix/suffix wrappers + default tone.
# ---------------------------------------------------------------------------
class PromptTemplate(models.Model):
    """User-owned prompt wrapper.

    A template wraps the raw input with optional ``prompt_prefix`` and
    ``prompt_suffix`` strings, and may force a default tone. Templates are
    scoped per user; the optional ``is_default=True`` flag marks the one
    template applied automatically when the client doesn't pass an explicit
    template_id (only one default per user, enforced via a partial unique
    constraint).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ai_templates",
        null=True, blank=True,
        help_text="Owner of the template. ``null`` = built-in / public template.",
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    default_tone = models.CharField(
        max_length=32,
        choices=_tones(),
        default=_default_tone,
    )
    prompt_prefix = models.TextField(
        blank=True,
        help_text="Prepended to the user input before the AI call.",
    )
    prompt_suffix = models.TextField(
        blank=True,
        help_text="Appended to the user input before the AI call.",
    )
    is_default = models.BooleanField(default=False, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ai_prompt_template"
        ordering = ("-is_default", "-updated_at")
        constraints = [
            # At most one default template per user.
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(is_default=True),
                name="ai_unique_default_template_per_user",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "is_default"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.default_tone})"


# ---------------------------------------------------------------------------
# Generation — audit record of every LLM call.
# ---------------------------------------------------------------------------
class Generation(models.Model):
    """One LLM call: input → output, plus accounting metadata.

    Either ``user`` or ``session_key`` must be set — never both empty.
    This is enforced via a check constraint so accounting code can always
    attribute a generation to *someone*.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="ai_generations",
    )
    session_key = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="Django session key for anonymous trials.",
    )

    template = models.ForeignKey(
        PromptTemplate,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="generations",
    )

    input_text = models.TextField()
    output_text = models.TextField()
    tone = models.CharField(
        max_length=32,
        choices=_tones(),
        default=_default_tone,
    )

    # --- accounting ----------------------------------------------------
    provider = models.CharField(
        max_length=32, blank=True,
        help_text="Provider key (e.g. 'anthropic', 'openai').",
    )
    model = models.CharField(
        max_length=64, blank=True,
        help_text="Model identifier returned by the provider.",
    )
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cost_usd = models.DecimalField(
        max_digits=10, decimal_places=6, default=0,
        help_text="Estimated cost in USD. Computed by the provider.",
    )

    # --- RAG hook ------------------------------------------------------
    retrieved_memory_ids = models.JSONField(
        default=list, blank=True,
        help_text="IDs of RAG chunks injected into the prompt, if any.",
    )

    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "ai_generation"
        ordering = ("-created_at",)
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(user__isnull=False)
                    | ~models.Q(session_key="")
                ),
                name="ai_generation_user_or_session",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["session_key", "-created_at"]),
        ]

    def __str__(self) -> str:
        who = self.user_id or f"sess:{self.session_key[:8]}"
        return f"Generation #{self.pk} by {who} ({self.tone})"

    @property
    def total_tokens(self) -> int:
        return int(self.input_tokens) + int(self.output_tokens)


# Re-exported helpers for views / serializers that want the canonical list.
def get_supported_tones() -> Iterable[tuple[str, str]]:
    return _tones()
