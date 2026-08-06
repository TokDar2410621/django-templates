"""Test fixtures + Stripe SDK mocks.

The Stripe SDK is mocked at the module level so ``compute_payout``
tests can run without the package installed in CI, and ``create_payout``
tests can assert on what we'd HAVE sent to Stripe.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest
from django.contrib.auth import get_user_model

from stripe_connect_multivendor.models import Affiliate, Partner


# ---------------------------------------------------------------------------
# Stripe SDK mock — installed before the services module is imported.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def stub_stripe(monkeypatch):
    """Provide a fake ``stripe`` module so service tests don't need the SDK.

    Yields the mock so tests can assert on call args / set return values
    on a per-test basis. Exposes ``Transfer.create``, ``Account.modify``,
    ``Account.retrieve``, ``OAuth.token``, ``Webhook.construct_event``
    and a minimal ``error`` namespace.
    """
    fake = types.ModuleType("stripe")

    fake.api_key = None

    # error namespace --------------------------------------------------
    class StripeError(Exception):
        pass

    class PermissionError_(StripeError):  # noqa: N801 — mirroring stripe naming
        pass

    class SignatureVerificationError(StripeError):
        pass

    error_module = types.SimpleNamespace(
        StripeError=StripeError,
        PermissionError=PermissionError_,
        SignatureVerificationError=SignatureVerificationError,
    )
    fake.error = error_module
    fake.StripeError = StripeError
    fake.SignatureVerificationError = SignatureVerificationError

    # API surface ------------------------------------------------------
    fake.Transfer = MagicMock(name="stripe.Transfer")
    fake.Transfer.create = MagicMock(
        return_value=MagicMock(id="tr_test_123"),
    )
    fake.Transfer.create_reversal = MagicMock(
        return_value=MagicMock(id="trr_test_456"),
    )
    fake.Account = MagicMock(name="stripe.Account")
    fake.Account.modify = MagicMock(
        return_value={
            "id": "acct_test",
            "capabilities": {"transfers": "active"},
            "charges_enabled": True,
            "payouts_enabled": True,
        },
    )
    fake.Account.retrieve = MagicMock(
        return_value={
            "id": "acct_test",
            "capabilities": {"transfers": "active"},
            "charges_enabled": True,
            "payouts_enabled": True,
        },
    )
    fake.OAuth = MagicMock(name="stripe.OAuth")
    fake.OAuth.token = MagicMock(
        return_value={"stripe_user_id": "acct_test_oauth"},
    )
    fake.Webhook = MagicMock(name="stripe.Webhook")
    fake.Webhook.construct_event = MagicMock()

    monkeypatch.setitem(sys.modules, "stripe", fake)
    # Provide a sane default secret so _require_secret_key passes.
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake")
    from django.conf import settings as dj_settings
    dj_settings.STRIPE_SECRET_KEY = "sk_test_fake"
    dj_settings.STRIPE_WEBHOOK_SECRET = "whsec_fake"
    dj_settings.STRIPE_CONNECT_CLIENT_ID = "ca_test_fake"
    yield fake


# ---------------------------------------------------------------------------
# User + Partner + Affiliate fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def user(db):
    User = get_user_model()
    return User.objects.create_user(
        username="alice",
        email="alice@example.com",
        password="pwpwpwpw",
    )


@pytest.fixture
def other_user(db):
    User = get_user_model()
    return User.objects.create_user(
        username="bob",
        email="bob@example.com",
        password="pwpwpwpw",
    )


@pytest.fixture
def partner(db, user) -> Partner:
    """A partner with Connect already linked and verified."""
    return Partner.objects.create(
        user=user,
        display_name="Alice's Studio",
        payout_email="alice@example.com",
        default_share_bps=7000,
        flat_per_order_cents=0,
        stripe_account_id="acct_alice",
        stripe_account_verified=True,
        active=True,
    )


@pytest.fixture
def unverified_partner(db, other_user) -> Partner:
    """A partner who hasn't completed Connect onboarding yet."""
    return Partner.objects.create(
        user=other_user,
        display_name="Bob's Goods",
        default_share_bps=8000,
    )


@pytest.fixture
def affiliate(db, other_user) -> Affiliate:
    return Affiliate.objects.create(
        user=other_user,
        code="ALICE10",
        commission_bps=1000,
    )
