"""Service layer for conversational_ai_engine.

Orchestrates provider call + persona injection + template wrapping +
optional RAG retrieval + audit logging + signal dispatch.

Why a service module?
---------------------

* Views stay thin — they validate input and return a serializer.
* Tests can call :func:`generate` directly without DRF plumbing.
* The signal is fired in exactly one place, so billing/analytics receivers
  never see partial data.

The :func:`generate` function is the only entry point that should be used
from outside the app. ``record_generation`` is exported for completeness
(useful if a project wants to log a generation produced by code outside
this app — e.g. a CLI tool — without re-running the full pipeline).
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Callable, Iterator, Optional

from django.conf import settings
from django.db import transaction
from django.utils.module_loading import import_string

from .models import Generation, PersonaContext, PromptTemplate
from .providers import GenerationResult, ProviderMessage, get_provider
from .signals import on_generation_complete

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def generate(
    *,
    user=None,
    session_key: str = "",
    prompt: str,
    persona: Optional[PersonaContext] = None,
    template: Optional[PromptTemplate] = None,
    tone: Optional[str] = None,
    vision_images: Optional[list[dict]] = None,
    system_prompt: str = "",
    provider_key: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: int = 1024,
    temperature: float = 0.7,
    stream: bool = False,
) -> GenerationResult | Iterator[str]:
    """Run a generation end-to-end.

    Returns a :class:`GenerationResult` when ``stream=False``; otherwise
    returns an iterator of text deltas (the view layer wraps this in SSE).

    The persisted :class:`Generation` row is created BEFORE the signal
    fires — receivers always see a saved instance.
    """
    if not prompt and not vision_images:
        raise ValueError("Either `prompt` or `vision_images` must be provided.")

    if not user_or_session_present(user, session_key):
        raise ValueError("Either `user` or `session_key` must be set.")

    # ---- build the prompt -------------------------------------------------
    wrapped_input = _apply_template(prompt, template)
    retrieved, rag_context = _retrieve_rag_context(user, prompt)
    full_input = _prepend_rag(rag_context, wrapped_input)

    final_system = _build_system_prompt(system_prompt, persona, tone)

    messages = [ProviderMessage(role="user", content=full_input)]

    provider = get_provider(provider_key)

    if stream:
        return _stream(
            provider=provider,
            user=user,
            session_key=session_key,
            template=template,
            tone=tone,
            full_input=full_input,
            final_system=final_system,
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            vision_images=vision_images,
            retrieved=retrieved,
        )

    result = provider.generate(
        system=final_system,
        messages=messages,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        vision_images=vision_images,
    )
    record_generation(
        user=user,
        session_key=session_key,
        template=template,
        tone=tone,
        input_text=full_input,
        output_text=result.text,
        provider_key=provider.key,
        model=result.model or (model or ""),
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cost_usd=result.cost_usd,
        retrieved_memory_ids=[r.get("id") for r in retrieved if r.get("id") is not None],
        metadata=result.metadata,
    )
    return result


def record_generation(
    *,
    user,
    session_key: str,
    template: Optional[PromptTemplate],
    tone: Optional[str],
    input_text: str,
    output_text: str,
    provider_key: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: Decimal,
    retrieved_memory_ids: Optional[list] = None,
    metadata: Optional[dict] = None,
) -> Generation:
    """Persist a Generation row + fire :data:`on_generation_complete`.

    Called automatically by :func:`generate`. Exposed for projects that
    want to record generations produced outside the engine.
    """
    with transaction.atomic():
        gen = Generation.objects.create(
            user=user if user_is_authenticated(user) else None,
            session_key=session_key or "",
            template=template,
            tone=tone or _default_tone_value(),
            input_text=input_text,
            output_text=output_text,
            provider=provider_key,
            model=model,
            input_tokens=int(input_tokens or 0),
            output_tokens=int(output_tokens or 0),
            cost_usd=cost_usd or Decimal("0"),
            retrieved_memory_ids=retrieved_memory_ids or [],
            metadata=metadata or {},
        )
    logger.info(
        "ai.generated id=%s user=%s tokens=%s+%s cost=%s",
        gen.pk, getattr(user, "pk", None),
        gen.input_tokens, gen.output_tokens, gen.cost_usd,
    )
    on_generation_complete.send(
        sender=Generation,
        user=user if user_is_authenticated(user) else None,
        generation=gen,
        input_tokens=gen.input_tokens,
        output_tokens=gen.output_tokens,
        cost_usd=gen.cost_usd,
    )
    return gen


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def user_is_authenticated(user) -> bool:
    return user is not None and getattr(user, "is_authenticated", False)


def user_or_session_present(user, session_key: str) -> bool:
    return user_is_authenticated(user) or bool(session_key)


def _default_tone_value() -> str:
    from .models import _default_tone
    return _default_tone()


def _apply_template(prompt: str, template: Optional[PromptTemplate]) -> str:
    if template is None:
        return prompt
    prefix = (template.prompt_prefix or "").strip()
    suffix = (template.prompt_suffix or "").strip()
    parts = [p for p in (prefix, prompt, suffix) if p]
    return "\n\n".join(parts)


def _build_system_prompt(
    base_system: str,
    persona: Optional[PersonaContext],
    tone: Optional[str],
) -> str:
    fragments: list[str] = []
    if base_system:
        fragments.append(base_system)
    if tone:
        fragments.append(f"Adopt a {tone} tone in your response.")
    if persona is not None:
        ctx = persona.build_prompt_context()
        if ctx:
            fragments.append(ctx)
    return "\n\n".join(fragments).strip()


# ---- RAG hook -------------------------------------------------------------
def _resolve_rag_backend() -> Optional[Callable]:
    """Return the configured retrieval callable, or ``None`` if disabled.

    ``settings.AI_RAG_RETRIEVAL_BACKEND`` may be:

    * ``None`` (default) — no retrieval
    * A callable ``(user, query) -> list[dict]``
    * A dotted path string resolved with :func:`import_string`
    """
    backend = getattr(settings, "AI_RAG_RETRIEVAL_BACKEND", None)
    if backend is None:
        return None
    if isinstance(backend, str):
        return import_string(backend)
    return backend


def _retrieve_rag_context(user, query: str) -> tuple[list[dict], str]:
    backend = _resolve_rag_backend()
    if backend is None:
        return [], ""
    try:
        retrieved = backend(user=user, query=query) or []
    except Exception:
        logger.exception("AI_RAG_RETRIEVAL_BACKEND failed; falling back to no-RAG")
        return [], ""
    if not retrieved:
        return [], ""
    body = "\n\n".join(
        chunk.get("text", "") for chunk in retrieved if chunk.get("text")
    )
    formatted = f"CONTEXT:\n{body}" if body else ""
    return list(retrieved), formatted


def _prepend_rag(rag_context: str, user_input: str) -> str:
    if not rag_context:
        return user_input
    return f"{rag_context}\n\n---\n\n{user_input}"


# ---- Streaming ------------------------------------------------------------
def _stream(
    *,
    provider,
    user,
    session_key: str,
    template: Optional[PromptTemplate],
    tone: Optional[str],
    full_input: str,
    final_system: str,
    messages: list[ProviderMessage],
    model: Optional[str],
    max_tokens: int,
    temperature: float,
    vision_images: Optional[list[dict]],
    retrieved: list[dict],
) -> Iterator[str]:
    """Stream chunks while collecting the full output to persist at the end."""
    chunks: list[str] = []
    try:
        for delta in provider.stream_generate(
            system=final_system,
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            vision_images=vision_images,
        ):
            chunks.append(delta)
            yield delta
    finally:
        usage = provider.last_usage()
        record_generation(
            user=user,
            session_key=session_key,
            template=template,
            tone=tone,
            input_text=full_input,
            output_text="".join(chunks),
            provider_key=provider.key,
            model=usage.model or (model or ""),
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=usage.cost_usd,
            retrieved_memory_ids=[r.get("id") for r in retrieved if r.get("id") is not None],
            metadata=usage.metadata,
        )
