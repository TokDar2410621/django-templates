"""DRF serializers for newsletter_engine.

Read serializers are listed first, write serializers second. The public
endpoints (subscribe, confirm, unsubscribe) use bespoke serializers that
DON'T expose the Subscriber model directly — that's deliberate, so a
public API caller can't enumerate other tenants' subscribers via DRF's
nested-write conventions.
"""
from __future__ import annotations

from rest_framework import serializers

from .models import (
    Automation,
    AutomationEnrollment,
    AutomationStep,
    Campaign,
    Delivery,
    MailingList,
    Membership,
    Segment,
    Subscriber,
    Tag,
)


# ---------------------------------------------------------------------------
# Subscriber + memberships + tags (admin-side)
# ---------------------------------------------------------------------------
class SubscriberSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subscriber
        fields = (
            "id", "email", "name", "status", "confirmed_at",
            "unsubscribed_at", "source", "consented_marketing", "locale",
            "metadata", "bounce_count", "last_bounce_at",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "status", "confirmed_at", "unsubscribed_at",
            "bounce_count", "last_bounce_at", "created_at", "updated_at",
        )


class MailingListSerializer(serializers.ModelSerializer):
    class Meta:
        model = MailingList
        fields = (
            "id", "name", "slug", "description", "is_active",
            "default_from_role", "default_reply_to",
            "requires_double_opt_in", "created_at",
        )
        read_only_fields = ("id", "created_at")


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ("id", "name", "created_at")
        read_only_fields = ("id", "created_at")


class MembershipSerializer(serializers.ModelSerializer):
    class Meta:
        model = Membership
        fields = (
            "id", "subscriber", "list", "status", "subscribed_at",
            "unsubscribed_at", "unsubscribe_reason",
        )
        read_only_fields = ("id", "subscribed_at")


# ---------------------------------------------------------------------------
# Segment
# ---------------------------------------------------------------------------
class SegmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Segment
        fields = (
            "id", "name", "list", "filters",
            "subscriber_count", "last_evaluated_at",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "subscriber_count", "last_evaluated_at",
            "created_at", "updated_at",
        )


class SegmentPreviewSerializer(serializers.Serializer):
    """Output of GET /segments/<id>/preview/ — count + a small sample."""
    count = serializers.IntegerField()
    sample = SubscriberSerializer(many=True)


# ---------------------------------------------------------------------------
# Campaign
# ---------------------------------------------------------------------------
class CampaignSerializer(serializers.ModelSerializer):
    class Meta:
        model = Campaign
        fields = (
            "id", "list", "segment", "subject", "html_body", "text_body",
            "status", "scheduled_at", "sent_at",
            "from_role", "from_email_override", "reply_to",
            "created_by", "created_at",
            "sent_count", "delivered_count", "open_count", "click_count",
            "bounce_count", "unsubscribe_count", "complaint_count",
        )
        read_only_fields = (
            "id", "status", "sent_at", "created_by", "created_at",
            "sent_count", "delivered_count", "open_count", "click_count",
            "bounce_count", "unsubscribe_count", "complaint_count",
        )

    def validate(self, attrs: dict) -> dict:
        list_ = attrs.get("list")
        segment = attrs.get("segment")
        # On update, fall back to instance.
        if self.instance is not None:
            list_ = list_ or self.instance.list
            segment = segment or self.instance.segment
        if bool(list_) == bool(segment):
            raise serializers.ValidationError(
                "Exactly one of 'list' or 'segment' must be set."
            )
        return attrs


class CampaignStatsSerializer(serializers.Serializer):
    """Output of /campaigns/<id>/stats/ — live counts from the Delivery table."""
    by_status = serializers.DictField(child=serializers.IntegerField())
    sent_count = serializers.IntegerField()
    open_count = serializers.IntegerField()
    click_count = serializers.IntegerField()
    bounce_count = serializers.IntegerField()
    complaint_count = serializers.IntegerField()


# ---------------------------------------------------------------------------
# Automation
# ---------------------------------------------------------------------------
class AutomationStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = AutomationStep
        fields = (
            "id", "order", "delay_seconds", "subject",
            "html_body", "text_body", "condition", "created_at",
        )
        read_only_fields = ("id", "created_at")


class AutomationSerializer(serializers.ModelSerializer):
    steps = AutomationStepSerializer(many=True, read_only=True)

    class Meta:
        model = Automation
        fields = (
            "id", "name", "trigger", "trigger_config", "is_active",
            "created_at", "steps",
        )
        read_only_fields = ("id", "created_at", "steps")


class AutomationEnrollmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = AutomationEnrollment
        fields = (
            "id", "automation", "subscriber", "started_at",
            "last_step_index", "last_step_at",
            "completed_at", "cancelled_at", "cancellation_reason",
        )
        read_only_fields = fields  # purely read-only via API


# ---------------------------------------------------------------------------
# Public API serializers (no model exposure)
# ---------------------------------------------------------------------------
class PublicSubscribeSerializer(serializers.Serializer):
    """POST /api/newsletter/subscribe/"""
    email = serializers.EmailField()
    list_slug = serializers.SlugField(required=False, allow_blank=True)
    name = serializers.CharField(required=False, allow_blank=True, max_length=120)
    locale = serializers.CharField(required=False, allow_blank=True, max_length=10)
    consented_marketing = serializers.BooleanField(default=False)
    source = serializers.CharField(required=False, allow_blank=True, max_length=50)


class PublicPreferencesUpdateSerializer(serializers.Serializer):
    """POST /api/newsletter/preferences/"""
    token = serializers.CharField()
    list_slugs = serializers.ListField(
        child=serializers.SlugField(),
        help_text="The slugs of lists the subscriber wants to STAY on. Any "
                  "current memberships not in this list are unsubscribed.",
    )


# ---------------------------------------------------------------------------
# Delivery (read-only for audit)
# ---------------------------------------------------------------------------
class DeliverySerializer(serializers.ModelSerializer):
    class Meta:
        model = Delivery
        fields = (
            "id", "campaign", "subscriber", "status",
            "tracking_token", "provider_message_id",
            "sent_at", "delivered_at",
            "opened_at", "open_count", "last_opened_at",
            "clicked_at", "click_count", "last_clicked_at",
            "bounced_at", "error",
        )
        read_only_fields = fields
