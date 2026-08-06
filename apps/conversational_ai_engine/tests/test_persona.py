"""PersonaContext model + selector tests."""
from __future__ import annotations

import pytest

from conversational_ai_engine.models import PersonaContext
from conversational_ai_engine.selectors import get_persona


@pytest.mark.django_db
def test_persona_empty_has_no_context(user):
    persona = PersonaContext.objects.create(user=user)
    assert persona.has_context is False
    assert persona.build_prompt_context() == ""


@pytest.mark.django_db
def test_persona_build_prompt_context_includes_filled_fields(user):
    persona = PersonaContext.objects.create(
        user=user,
        role="Backend Engineer",
        industry="FinTech",
        writing_style="Direct, concrete.",
    )
    ctx = persona.build_prompt_context()
    assert "AUTHOR CONTEXT" in ctx
    assert "Backend Engineer" in ctx
    assert "FinTech" in ctx
    assert "Direct, concrete." in ctx
    # Empty fields must not appear.
    assert "Bio" not in ctx


@pytest.mark.django_db
def test_get_persona_returns_none_for_anonymous():
    assert get_persona(None) is None


@pytest.mark.django_db
def test_get_persona_returns_none_when_not_created(user):
    assert get_persona(user) is None


@pytest.mark.django_db
def test_get_persona_returns_instance_when_created(user):
    PersonaContext.objects.create(user=user, role="X")
    persona = get_persona(user)
    assert persona is not None
    assert persona.role == "X"
