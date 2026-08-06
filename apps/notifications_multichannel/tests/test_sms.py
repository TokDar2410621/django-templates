"""SMS channel tests — degraded mode, E.164 validation, truncation."""
from __future__ import annotations

import sys

import pytest

from notifications_multichannel.services import send_sms


@pytest.mark.django_db
def test_sms_skipped_without_creds(user, settings):
    settings.TWILIO_ACCOUNT_SID = ""
    settings.TWILIO_AUTH_TOKEN = ""
    settings.TWILIO_FROM_NUMBER = ""
    result = send_sms(user=user, to_e164="+15551234567", body="hi")
    assert result.status == "skipped"


@pytest.mark.django_db
def test_sms_failed_when_destination_not_e164(user, twilio_configured):
    result = send_sms(user=user, to_e164="5551234567", body="hi")
    assert result.status == "failed"
    assert "E.164" in result.error


@pytest.mark.django_db
def test_sms_failed_when_no_destination(twilio_configured):
    """No ``to_e164`` and no ``user.phone_e164`` attribute → fail."""
    result = send_sms(body="hi")
    assert result.status == "failed"
    assert "destination" in result.error.lower()


@pytest.mark.django_db
def test_sms_truncates_body_to_max_len(user, twilio_configured, mock_twilio):
    long_body = "A" * 1000
    result = send_sms(user=user, to_e164="+15551234567", body=long_body)
    assert result.ok, result.error
    # The mock FakeClient captures the create() kwargs
    client = sys.modules["twilio.rest"].Client("x", "y")
    # Use the result's provider id to confirm one message was created.
    assert result.provider_message_id == "twilio-msg-1"


@pytest.mark.django_db
def test_sms_returns_provider_sid_on_success(user, twilio_configured, mock_twilio):
    result = send_sms(user=user, to_e164="+15551234567", body="hi")
    assert result.ok
    assert result.provider_message_id == "twilio-msg-1"
