"""DRF serializers for conversational_ai_engine.

Schema:

* :class:`PersonaContextSerializer` — full read/write of the user's persona.
* :class:`PromptTemplateSerializer` — read/write of templates.
* :class:`GenerationSerializer` — read-only audit row (no exposing of
  internal metadata to the client).
* :class:`GenerateRequestSerializer` — validates an incoming
  ``POST /generate/`` request.
"""
from __future__ import annotations

from rest_framework import serializers

from .models import Generation, PersonaContext, PromptTemplate, _tones


class PersonaContextSerializer(serializers.ModelSerializer):
    class Meta:
        model = PersonaContext
        fields = (
            "role", "industry", "expertise",
            "target_audience", "writing_style", "bio",
            "examples", "additional_context",
            "created_at", "updated_at",
        )
        read_only_fields = ("created_at", "updated_at")


class PromptTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PromptTemplate
        fields = (
            "id", "name", "description",
            "default_tone", "prompt_prefix", "prompt_suffix",
            "is_default", "created_at", "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class GenerationSerializer(serializers.ModelSerializer):
    total_tokens = serializers.IntegerField(read_only=True)

    class Meta:
        model = Generation
        fields = (
            "id", "input_text", "output_text", "tone",
            "provider", "model",
            "input_tokens", "output_tokens", "total_tokens", "cost_usd",
            "retrieved_memory_ids",
            "created_at",
        )
        read_only_fields = fields


class GenerateRequestSerializer(serializers.Serializer):
    """Input for ``POST /generate/`` and ``POST /generate/stream/``.

    ``vision_images`` is a list of ``{"data_base64": "...",
    "media_type": "image/png"}`` dicts. The view layer also accepts
    ``multipart/form-data`` with ``images`` uploads — see ``views.py``.
    """
    prompt = serializers.CharField(allow_blank=True, required=False, default="")
    tone = serializers.ChoiceField(
        choices=_tones(), required=False, allow_blank=True, default="",
    )
    template_id = serializers.IntegerField(required=False, allow_null=True)
    system_prompt = serializers.CharField(
        required=False, allow_blank=True, default="",
    )
    model = serializers.CharField(required=False, allow_blank=True, default="")
    max_tokens = serializers.IntegerField(required=False, min_value=1, max_value=8192, default=1024)
    temperature = serializers.FloatField(
        required=False, min_value=0.0, max_value=2.0, default=0.7,
    )
    vision_images = serializers.ListField(
        child=serializers.DictField(), required=False, allow_empty=True,
    )

    def validate(self, attrs: dict) -> dict:
        prompt = (attrs.get("prompt") or "").strip()
        if not prompt and not attrs.get("vision_images"):
            raise serializers.ValidationError(
                "Either `prompt` or `vision_images` must be provided."
            )
        return attrs
