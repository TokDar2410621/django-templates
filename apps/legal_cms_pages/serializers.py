"""Serializers for the public read API."""
from __future__ import annotations

from rest_framework import serializers

from .models import LegalDocument
from .services import render_html


class LegalDocumentDetailSerializer(serializers.ModelSerializer):
    """Full document — what GET /api/legal/<kind>/ returns."""

    body_html = serializers.SerializerMethodField()

    class Meta:
        model = LegalDocument
        fields = (
            "id",
            "kind",
            "language",
            "title",
            "body_markdown",
            "body_html",
            "effective_from",
            "updated_at",
        )

    def get_body_html(self, obj: LegalDocument) -> str:
        return render_html(obj.body_markdown)


class LegalDocumentIndexSerializer(serializers.ModelSerializer):
    """Index — what GET /api/legal/ returns (without the body)."""

    class Meta:
        model = LegalDocument
        fields = ("kind", "language", "title", "effective_from", "updated_at")
