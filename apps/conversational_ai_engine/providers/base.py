"""Abstract :class:`AIProvider` contract.

Why an abstraction layer?
-------------------------

Most apps want to swap LLM vendors without touching the call sites
(generation view, signals, billing hook). The provider abstraction hides
the SDK-specific glue (Anthropic ``client.messages.create``, OpenAI
``client.chat.completions.create``, Gemini ``models.generate_content``) and
returns a uniform :class:`GenerationResult`.

A provider is responsible for:

* Calling the underlying API (HTTP, SDK, gRPC — whatever).
* Returning a :class:`GenerationResult` with the produced text + token
  counts + USD cost estimate.
* Streaming via :meth:`stream_generate` — yields raw text deltas.
* Failing with a *typed* exception subclass that the view layer can map
  to a clean HTTP code: :class:`ProviderRateLimit`, :class:`ProviderAuth`,
  :class:`ProviderUnavailable`, :class:`ProviderError`.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterator, Optional

from django.conf import settings


# ---------------------------------------------------------------------------
# Data carriers
# ---------------------------------------------------------------------------
@dataclass
class ProviderMessage:
    """One message in a multi-turn conversation.

    ``role`` is ``"user"`` or ``"assistant"``. ``content`` is plain text;
    inline images (vision) are passed through the separate
    ``vision_images`` parameter on :meth:`AIProvider.generate` because each
    provider encodes them differently.
    """
    role: str
    content: str


@dataclass
class GenerationResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    model: str = ""
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class ProviderError(Exception):
    """Generic provider failure — maps to HTTP 500 in the view."""


class ProviderAuth(ProviderError):
    """Bad / missing API key — maps to HTTP 401."""


class ProviderRateLimit(ProviderError):
    """Rate-limited by upstream — maps to HTTP 429."""


class ProviderUnavailable(ProviderError):
    """Upstream is down — maps to HTTP 503."""


# ---------------------------------------------------------------------------
# Abstract class
# ---------------------------------------------------------------------------
class AIProvider(abc.ABC):
    """Base provider contract.

    Subclasses must implement :meth:`generate` and :meth:`stream_generate`.
    All other concerns (retries, observability, billing) are handled by the
    service layer — providers stay focused on the API call.
    """

    #: Short, machine-readable key (e.g. ``"anthropic"``). Used for routing
    #: and for the ``Generation.provider`` audit column.
    key: str = ""

    #: Default model identifier when the caller doesn't pass one explicitly.
    default_model: str = ""

    # ------------------------------------------------------------------
    # Required interface
    # ------------------------------------------------------------------
    @abc.abstractmethod
    def generate(
        self,
        *,
        system: str,
        messages: list[ProviderMessage],
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        vision_images: Optional[list[dict]] = None,
        prompt_caching: bool = True,
    ) -> GenerationResult:
        """Run a single non-streaming generation.

        ``vision_images`` is a list of ``{"data": <bytes-or-base64>,
        "media_type": "image/png"}`` dicts. Providers that don't support
        vision should silently drop them rather than raise.
        """

    @abc.abstractmethod
    def stream_generate(
        self,
        *,
        system: str,
        messages: list[ProviderMessage],
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        vision_images: Optional[list[dict]] = None,
        prompt_caching: bool = True,
    ) -> Iterator[str]:
        """Yield text chunks as the model produces them.

        After exhaustion, callers should read :meth:`last_usage` for token
        counts (streaming APIs typically surface usage only at the end).
        """

    # ------------------------------------------------------------------
    # Optional hooks
    # ------------------------------------------------------------------
    def last_usage(self) -> GenerationResult:
        """Return the usage stats from the most recent streaming call.

        Default implementation returns zeros — providers that can report
        streaming token counts should override.
        """
        return GenerationResult(text="")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _setting(name: str, default=None):
        return getattr(settings, name, default)
