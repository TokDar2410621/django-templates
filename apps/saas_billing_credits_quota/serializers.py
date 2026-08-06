"""Serializers for the billing read API + consume endpoint."""
from __future__ import annotations

from rest_framework import serializers

from .models import CreditBalance, CreditTransaction, Subscription
from .selectors import effective_limit, monthly_count, plan_limits


class CreditTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreditTransaction
        fields = (
            "id",
            "amount",
            "kind",
            "resource_key",
            "stripe_session_id",
            "description",
            "created_at",
        )
        read_only_fields = fields


class CreditBalanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreditBalance
        fields = ("balance", "updated_at")
        read_only_fields = fields


class SubscriptionSerializer(serializers.ModelSerializer):
    """Verbose subscription view — includes computed limits + per-resource
    remaining usage so the frontend doesn't have to roll its own math.

    The ``usage`` dict keys are the resource keys defined in
    ``SAAS_PLAN_LIMITS[plan]`` so the same view works for any caller's
    resource set.
    """

    is_paid = serializers.BooleanField(read_only=True)
    limits = serializers.SerializerMethodField()
    usage = serializers.SerializerMethodField()
    balance = serializers.SerializerMethodField()

    class Meta:
        model = Subscription
        fields = (
            "plan",
            "status",
            "is_paid",
            "current_period_end",
            "cancel_at_period_end",
            "limits",
            "usage",
            "balance",
            "updated_at",
        )
        read_only_fields = fields

    def get_limits(self, obj: Subscription) -> dict[str, int | None]:
        try:
            return plan_limits(obj.plan)
        except Exception:
            return {}

    def get_usage(self, obj: Subscription) -> dict[str, dict[str, int | None]]:
        try:
            limits = plan_limits(obj.plan)
        except Exception:
            return {}
        out: dict[str, dict[str, int | None]] = {}
        for resource_key, limit in limits.items():
            used = monthly_count(obj.user, resource_key)
            remaining = effective_limit(obj.user, resource_key)
            out[resource_key] = {
                "used": used,
                "limit": limit,            # None = unlimited
                "effective_remaining": remaining,
            }
        return out

    def get_balance(self, obj: Subscription) -> int:
        from .selectors import get_balance
        return get_balance(obj.user)


class ConsumeSerializer(serializers.Serializer):
    """Input schema for POST /consume/ — drives ``services.consume``."""

    resource_key = serializers.CharField(max_length=64)
    n = serializers.IntegerField(min_value=1, default=1)


class CheckoutSerializer(serializers.Serializer):
    """Input schema for POST /checkout/ — subscription OR one-time pack."""

    mode = serializers.ChoiceField(choices=("subscription", "payment"))
    # Subscription mode: plan slug; payment mode: pack slug. Validated in the view.
    sku = serializers.CharField(max_length=64)
