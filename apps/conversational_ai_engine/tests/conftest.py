"""Pytest fixtures + a deterministic FakeAIProvider.

The real Anthropic provider is exercised by integration tests outside the
template; here we use a deterministic fake so unit tests never hit the
network. ``FakeAIProvider`` echoes the user input back with a prefix and
counts tokens by splitting on whitespace — predictable, fast, hermetic.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Iterator, Optional

import pytest
from django.contrib.auth import get_user_model

from conversational_ai_engine.providers import PROVIDERS
from conversational_ai_engine.providers.base import (
    AIProvider,
    GenerationResult,
    ProviderMessage,
)


class FakeAIProvider(AIProvider):
    """Deterministic echo-style provider for tests."""

    key = "fake"
    default_model = "fake-model"

    def __init__(self) -> None:
        self._last_usage = GenerationResult(text="")

    @staticmethod
    def _count_tokens(text: str) -> int:
        return len(text.split()) if text else 0

    def generate(
        self,
        *,
        system: str,
        messages: list[ProviderMessage],
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        vision_images=None,
        prompt_caching: bool = True,
    ) -> GenerationResult:
        user_text = messages[-1].content if messages else ""
        out_text = f"ECHO: {user_text}"
        in_tokens = self._count_tokens(system) + self._count_tokens(user_text)
        out_tokens = self._count_tokens(out_text)
        return GenerationResult(
            text=out_text,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            cost_usd=Decimal("0.000001") * Decimal(in_tokens + out_tokens),
            model=model or self.default_model,
            metadata={"fake": True, "system_seen": system, "vision": bool(vision_images)},
        )

    def stream_generate(
        self,
        *,
        system: str,
        messages: list[ProviderMessage],
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        vision_images=None,
        prompt_caching: bool = True,
    ) -> Iterator[str]:
        user_text = messages[-1].content if messages else ""
        chunks = [f"ECHO: ", user_text]
        for c in chunks:
            yield c
        self._last_usage = GenerationResult(
            text="",
            input_tokens=self._count_tokens(system) + self._count_tokens(user_text),
            output_tokens=self._count_tokens("".join(chunks)),
            cost_usd=Decimal("0.000002"),
            model=model or self.default_model,
            metadata={"fake": True, "streamed": True},
        )

    def last_usage(self) -> GenerationResult:
        return self._last_usage


@pytest.fixture(autouse=True)
def use_fake_provider(monkeypatch):
    """Force every test in this directory to use the fake provider."""
    PROVIDERS["fake"] = FakeAIProvider
    monkeypatch.setattr(
        "django.conf.settings.AI_DEFAULT_PROVIDER",
        "fake",
        raising=False,
    )
    yield


@pytest.fixture
def user(db):
    User = get_user_model()
    return User.objects.create_user(
        username="aitester",
        email="aitester@example.com",
        password="pwpwpwpw",
    )


@pytest.fixture
def other_user(db):
    User = get_user_model()
    return User.objects.create_user(
        username="other",
        email="other@example.com",
        password="pwpwpwpw",
    )
