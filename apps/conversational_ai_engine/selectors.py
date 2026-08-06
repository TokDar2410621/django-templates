"""Read-only queries for conversational_ai_engine.

Selectors return querysets or single instances. They never mutate state —
mutations live in ``services.py``.
"""
from __future__ import annotations

from typing import Optional

from django.db.models import QuerySet

from .models import Generation, PersonaContext, PromptTemplate


def get_persona(user) -> Optional[PersonaContext]:
    """Return the user's persona, or ``None`` if not yet created."""
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    return PersonaContext.objects.filter(user=user).first()


def list_user_templates(user) -> QuerySet[PromptTemplate]:
    """User-owned templates + globally available built-ins (user__isnull)."""
    if user is None or not getattr(user, "is_authenticated", False):
        return PromptTemplate.objects.filter(user__isnull=True)
    return PromptTemplate.objects.filter(user=user) | PromptTemplate.objects.filter(
        user__isnull=True,
    )


def get_default_template(user) -> Optional[PromptTemplate]:
    """The user's default template, falling back to a built-in default."""
    if user is not None and getattr(user, "is_authenticated", False):
        owned = PromptTemplate.objects.filter(user=user, is_default=True).first()
        if owned:
            return owned
    return PromptTemplate.objects.filter(
        user__isnull=True, is_default=True,
    ).first()


def recent_generations(user, n: int = 10) -> QuerySet[Generation]:
    """Most recent generations for the given user.

    Authenticated user: queries by ``user``. Anonymous: returns an empty qs
    (callers should use ``recent_generations_for_session`` instead).
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return Generation.objects.none()
    return Generation.objects.filter(user=user).order_by("-created_at")[:n]


def recent_generations_for_session(session_key: str, n: int = 10) -> QuerySet[Generation]:
    """Anonymous lookup — used for trial mode."""
    if not session_key:
        return Generation.objects.none()
    return Generation.objects.filter(
        session_key=session_key,
    ).order_by("-created_at")[:n]
