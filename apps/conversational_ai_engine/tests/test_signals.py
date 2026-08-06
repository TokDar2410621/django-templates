"""Tests for ``on_generation_complete``."""
from __future__ import annotations

import pytest

from conversational_ai_engine.services import generate
from conversational_ai_engine.signals import on_generation_complete


@pytest.mark.django_db
def test_signal_fires_with_user_and_generation(user):
    received = {}

    def receiver(sender, *, user, generation, input_tokens, output_tokens, cost_usd, **kwargs):
        received["user"] = user
        received["generation"] = generation
        received["input_tokens"] = input_tokens
        received["output_tokens"] = output_tokens
        received["cost_usd"] = cost_usd

    on_generation_complete.connect(receiver, dispatch_uid="test-receiver")
    try:
        generate(user=user, prompt="Hello", provider_key="fake")
    finally:
        on_generation_complete.disconnect(dispatch_uid="test-receiver")

    assert received["user"] == user
    assert received["generation"].pk is not None
    assert received["input_tokens"] > 0
    assert received["output_tokens"] > 0


@pytest.mark.django_db
def test_signal_fires_with_user_none_for_anonymous():
    received = {}

    def receiver(sender, *, user, generation, **kwargs):
        received["user"] = user
        received["generation_user_id"] = generation.user_id

    on_generation_complete.connect(receiver, dispatch_uid="anon-receiver")
    try:
        generate(session_key="anon-xyz", prompt="trial", provider_key="fake")
    finally:
        on_generation_complete.disconnect(dispatch_uid="anon-receiver")

    assert received["user"] is None
    assert received["generation_user_id"] is None
