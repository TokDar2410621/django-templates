"""Anthropic Claude provider.

Default model: :data:`DEFAULT_MODEL` (``claude-sonnet-4-6``) — recent
Sonnet for the cost/perf sweet spot. Override per call with the
``model=`` kwarg, or globally via ``settings.AI_DEFAULT_MODEL``.

Upgrade option: ``claude-opus-4-7[1m]`` for tasks where output quality
beats cost concerns. Haiku is fine for cheap classification / routing.

Prompt caching
--------------

When ``prompt_caching=True`` (the default and ``settings.AI_PROMPT_CACHING``
default), the system prompt is marked with ``cache_control={"type":
"ephemeral"}`` so subsequent calls within ~5 min reuse the cache. Big win
when a long persona is injected.

Cost estimation
---------------

USD cost is approximated client-side from the returned ``usage`` block.
The rate table is intentionally a per-model dict so projects can override
without code change — set :data:`MODEL_RATES_PER_MILLION` from settings or
just edit this dict when Anthropic publishes a new price.
"""
from __future__ import annotations

import base64
import logging
from decimal import Decimal
from typing import Any, Iterator, Optional

from django.conf import settings

from .base import (
    AIProvider,
    GenerationResult,
    ProviderAuth,
    ProviderError,
    ProviderMessage,
    ProviderRateLimit,
    ProviderUnavailable,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-6"

# Approximate USD per million tokens. Override at project level by setting
# ``AI_MODEL_RATES_PER_MILLION = {"claude-sonnet-4-6": (3.0, 15.0), ...}``.
# Format: (input_rate, output_rate).
MODEL_RATES_PER_MILLION: dict[str, tuple[float, float]] = {
    # Sonnet (current default — adjust if Anthropic re-prices).
    "claude-sonnet-4-6": (3.0, 15.0),
    # Opus (upgrade path).
    "claude-opus-4-7":   (15.0, 75.0),
    # Haiku (cheap path).
    "claude-haiku-4-6":  (0.80, 4.0),
}


class AnthropicProvider(AIProvider):
    """Claude provider built on the official ``anthropic`` SDK."""

    key = "anthropic"
    default_model = DEFAULT_MODEL

    def __init__(self) -> None:
        api_key = self._setting("ANTHROPIC_API_KEY")
        if not api_key:
            # Defer the error to call-time so the app can boot without a key
            # (degraded mode) — tests, settings checks, etc.
            self._client = None
        else:
            try:
                import anthropic  # type: ignore[import-not-found]
            except ImportError as exc:  # pragma: no cover - missing optional dep
                raise ProviderError(
                    "The `anthropic` package is not installed. "
                    "Run `pip install anthropic>=0.34`."
                ) from exc
            self._anthropic_mod = anthropic
            self._client = anthropic.Anthropic(api_key=api_key)
        self._last_usage = GenerationResult(text="")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
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
        self._require_client()
        model_id = model or self._setting("AI_DEFAULT_MODEL") or self.default_model
        params = self._build_params(
            system=system,
            messages=messages,
            model=model_id,
            max_tokens=max_tokens,
            temperature=temperature,
            vision_images=vision_images,
            prompt_caching=prompt_caching,
        )
        try:
            response = self._client.messages.create(**params)
        except Exception as exc:  # noqa: BLE001
            self._raise_for_sdk_error(exc)

        text = "".join(
            block.text for block in response.content if getattr(block, "text", None)
        )
        input_tokens = int(getattr(response.usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(response.usage, "output_tokens", 0) or 0)
        cost = self._estimate_cost(model_id, input_tokens, output_tokens)

        return GenerationResult(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            model=model_id,
            metadata={
                "stop_reason": getattr(response, "stop_reason", None),
                "id": getattr(response, "id", None),
            },
        )

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
        self._require_client()
        model_id = model or self._setting("AI_DEFAULT_MODEL") or self.default_model
        params = self._build_params(
            system=system,
            messages=messages,
            model=model_id,
            max_tokens=max_tokens,
            temperature=temperature,
            vision_images=vision_images,
            prompt_caching=prompt_caching,
        )
        try:
            with self._client.messages.stream(**params) as stream:
                for text in stream.text_stream:
                    yield text
                final = stream.get_final_message()
        except Exception as exc:  # noqa: BLE001
            self._raise_for_sdk_error(exc)

        input_tokens = int(getattr(final.usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(final.usage, "output_tokens", 0) or 0)
        self._last_usage = GenerationResult(
            text="",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=self._estimate_cost(model_id, input_tokens, output_tokens),
            model=model_id,
            metadata={"stop_reason": getattr(final, "stop_reason", None)},
        )

    def last_usage(self) -> GenerationResult:
        return self._last_usage

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _require_client(self) -> None:
        if self._client is None:
            raise ProviderAuth(
                "ANTHROPIC_API_KEY is not configured. Set it in your "
                "environment or settings."
            )

    def _build_params(
        self,
        *,
        system: str,
        messages: list[ProviderMessage],
        model: str,
        max_tokens: int,
        temperature: float,
        vision_images: Optional[list[dict]],
        prompt_caching: bool,
    ) -> dict[str, Any]:
        # Convert the abstract messages to Anthropic format. The last user
        # message receives vision attachments when applicable so the model
        # actually sees them.
        anthropic_messages: list[dict[str, Any]] = []
        for i, m in enumerate(messages):
            block: dict[str, Any]
            is_last_user = (
                m.role == "user"
                and i == len(messages) - 1
                and vision_images
            )
            if is_last_user:
                content = self._build_vision_content(m.content, vision_images or [])
                block = {"role": "user", "content": content}
            else:
                block = {"role": m.role, "content": m.content}
            anthropic_messages.append(block)

        # Prompt caching — wrap the system prompt with cache_control so
        # repeated calls within ~5 min hit the cache.
        sys_param: Any = system
        cache_enabled = prompt_caching and self._setting("AI_PROMPT_CACHING", True)
        if cache_enabled and system:
            sys_param = [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]

        return {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": sys_param,
            "messages": anthropic_messages,
        }

    @staticmethod
    def _build_vision_content(text: str, images: list[dict]) -> list[dict]:
        content: list[dict] = []
        for img in images[:5]:  # provider hard cap — defend the call site
            data = img.get("data", "")
            if isinstance(data, (bytes, bytearray)):
                data = base64.standard_b64encode(data).decode("ascii")
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": img.get("media_type", "image/png"),
                    "data": data,
                },
            })
        if text:
            content.append({"type": "text", "text": text})
        return content

    def _estimate_cost(
        self, model: str, input_tokens: int, output_tokens: int,
    ) -> Decimal:
        rates = self._setting(
            "AI_MODEL_RATES_PER_MILLION", MODEL_RATES_PER_MILLION,
        ).get(model)
        if not rates:
            return Decimal("0")
        in_rate, out_rate = rates
        cost = (
            (Decimal(input_tokens) / Decimal(1_000_000)) * Decimal(str(in_rate))
            + (Decimal(output_tokens) / Decimal(1_000_000)) * Decimal(str(out_rate))
        )
        return cost.quantize(Decimal("0.000001"))

    def _raise_for_sdk_error(self, exc: BaseException) -> None:
        """Translate anthropic SDK exceptions to provider-level ones."""
        mod = getattr(self, "_anthropic_mod", None)
        if mod is not None:
            if isinstance(exc, getattr(mod, "RateLimitError", ())):
                raise ProviderRateLimit(str(exc)) from exc
            if isinstance(exc, getattr(mod, "AuthenticationError", ())):
                raise ProviderAuth(str(exc)) from exc
            if isinstance(exc, getattr(mod, "APIStatusError", ())):
                status_code = getattr(exc, "status_code", None)
                if status_code in (502, 503, 504):
                    raise ProviderUnavailable(str(exc)) from exc
        logger.exception("anthropic provider call failed")
        raise ProviderError(str(exc)) from exc
