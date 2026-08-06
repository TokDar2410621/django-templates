"""Pluggable AI provider implementations.

Loaders read ``settings.AI_DEFAULT_PROVIDER`` (default: ``"anthropic"``)
and dispatch to the matching subclass of :class:`AIProvider`.

Adding a provider
-----------------

1. Subclass :class:`AIProvider` (see ``providers/base.py``).
2. Implement :meth:`AIProvider.generate` and
   :meth:`AIProvider.stream_generate` (yields chunks of text).
3. Register the class in :data:`PROVIDERS` below.

OpenAI and Gemini are sketched as stubs — see ``providers/base.py`` for
the contract; both are easy to fill in.
"""
from __future__ import annotations

from typing import Type

from django.conf import settings

from .base import AIProvider, GenerationResult, ProviderMessage
from .anthropic import AnthropicProvider


# Registry — extend in your project by appending to AI_PROVIDERS in settings
# (mapping of provider key -> dotted path) and calling get_provider(key).
PROVIDERS: dict[str, Type[AIProvider]] = {
    "anthropic": AnthropicProvider,
}


def get_provider(key: str | None = None) -> AIProvider:
    """Instantiate the provider matching ``key`` (or the default).

    Looks up ``settings.AI_DEFAULT_PROVIDER`` when ``key`` is omitted, and
    falls back to ``"anthropic"`` if that setting is also unset.

    Projects can extend the registry via:

    .. code-block:: python

       # settings.py
       AI_PROVIDERS = {
           "openai":  "myproject.ai_providers.OpenAIProvider",
       }
    """
    provider_key = key or getattr(settings, "AI_DEFAULT_PROVIDER", "anthropic")

    # Allow project-level overrides via dotted-path mapping.
    extra = getattr(settings, "AI_PROVIDERS", None) or {}
    if provider_key in extra:
        from django.utils.module_loading import import_string
        cls = import_string(extra[provider_key])
        return cls()

    if provider_key not in PROVIDERS:
        raise ValueError(
            f"Unknown AI provider {provider_key!r}. "
            f"Available: {sorted(set(PROVIDERS) | set(extra))}"
        )
    return PROVIDERS[provider_key]()


__all__ = [
    "AIProvider",
    "AnthropicProvider",
    "GenerationResult",
    "ProviderMessage",
    "PROVIDERS",
    "get_provider",
]
