"""Service-level tests for ``generate()`` — happy path + 2 negatives."""
from __future__ import annotations

import pytest

from conversational_ai_engine.models import (
    Generation,
    PersonaContext,
    PromptTemplate,
)
from conversational_ai_engine.services import generate


@pytest.mark.django_db
def test_generate_happy_path_persists_generation(user):
    result = generate(
        user=user,
        prompt="Hello world",
        provider_key="fake",
    )
    assert result.text == "ECHO: Hello world"
    assert result.input_tokens > 0
    assert result.output_tokens > 0

    row = Generation.objects.get(user=user)
    assert row.input_text == "Hello world"
    assert row.output_text == "ECHO: Hello world"
    assert row.provider == "fake"
    assert row.model == "fake-model"


@pytest.mark.django_db
def test_generate_injects_persona_into_system_prompt(user):
    PersonaContext.objects.create(
        user=user, role="Backend Engineer", industry="FinTech",
    )
    from conversational_ai_engine.selectors import get_persona
    persona = get_persona(user)
    result = generate(
        user=user,
        persona=persona,
        prompt="Explain transactions.",
        provider_key="fake",
    )
    # FakeAIProvider drops the seen system prompt into metadata so we can
    # assert that the persona made it through.
    saw_system = result.metadata["system_seen"]
    assert "Backend Engineer" in saw_system
    assert "FinTech" in saw_system


@pytest.mark.django_db
def test_generate_applies_template_prefix_and_suffix(user):
    template = PromptTemplate.objects.create(
        user=user,
        name="Wrap",
        prompt_prefix="START.",
        prompt_suffix="END.",
    )
    result = generate(
        user=user,
        template=template,
        prompt="MIDDLE",
        provider_key="fake",
    )
    assert "START." in result.text
    assert "END." in result.text
    assert "MIDDLE" in result.text


@pytest.mark.django_db
def test_generate_with_anonymous_session_persists_with_session_key():
    result = generate(
        session_key="anon123",
        prompt="trial run",
        provider_key="fake",
    )
    row = Generation.objects.get(session_key="anon123")
    assert row.user_id is None
    assert row.input_text == "trial run"
    assert result.text == "ECHO: trial run"


# ---- Negatives ------------------------------------------------------------
@pytest.mark.django_db
def test_generate_without_user_or_session_raises():
    with pytest.raises(ValueError, match="user.*session_key"):
        generate(prompt="x", provider_key="fake")


@pytest.mark.django_db
def test_generate_without_prompt_or_images_raises(user):
    with pytest.raises(ValueError, match="prompt.*vision_images"):
        generate(user=user, prompt="", provider_key="fake")


# ---- RAG hook -------------------------------------------------------------
@pytest.mark.django_db
def test_generate_rag_backend_injects_retrieved_chunks(user, settings):
    def fake_backend(*, user, query):
        return [
            {"id": "chunk-1", "text": "Doc says A."},
            {"id": "chunk-2", "text": "Doc says B."},
        ]
    settings.AI_RAG_RETRIEVAL_BACKEND = fake_backend

    result = generate(
        user=user,
        prompt="Question?",
        provider_key="fake",
    )
    # ECHO sees the wrapped input — proves RAG was prepended.
    assert "CONTEXT:" in result.text
    assert "Doc says A." in result.text

    row = Generation.objects.get(user=user)
    assert row.retrieved_memory_ids == ["chunk-1", "chunk-2"]


@pytest.mark.django_db
def test_generate_rag_backend_failure_falls_back_to_no_rag(user, settings):
    def broken_backend(*, user, query):
        raise RuntimeError("boom")
    settings.AI_RAG_RETRIEVAL_BACKEND = broken_backend

    # Must not raise — the engine catches and continues without RAG.
    result = generate(user=user, prompt="Hi", provider_key="fake")
    assert "CONTEXT:" not in result.text


# ---- Streaming ------------------------------------------------------------
@pytest.mark.django_db
def test_generate_stream_yields_chunks_and_persists_at_end(user):
    chunks = list(generate(
        user=user,
        prompt="Hello",
        provider_key="fake",
        stream=True,
    ))
    assert "".join(chunks) == "ECHO: Hello"
    row = Generation.objects.get(user=user)
    assert row.output_text == "ECHO: Hello"
