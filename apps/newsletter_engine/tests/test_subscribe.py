"""Tests for the subscribe / confirm flow."""
from __future__ import annotations

import pytest

from newsletter_engine.exceptions import (
    SubscriberConflict,
    UnsubscribeTokenInvalid,
)
from newsletter_engine.models import Subscriber, UnsubscribeToken
from newsletter_engine.services.subscribers import (
    confirm_subscriber,
    subscribe,
)


@pytest.mark.django_db
def test_double_opt_in_creates_pending_subscriber_and_token(tenant, mailing_list):
    sub, token = subscribe(
        tenant=tenant,
        email="newperson@example.com",
        list=mailing_list,
        consented=True,
    )
    assert sub.status == Subscriber.STATUS_PENDING
    assert token is not None
    assert token.scope == "confirm"
    assert sub.consented_marketing is True


@pytest.mark.django_db
def test_open_list_immediately_confirms_subscriber(tenant, open_list):
    sub, token = subscribe(
        tenant=tenant,
        email="trusted@example.com",
        list=open_list,
    )
    assert sub.status == Subscriber.STATUS_CONFIRMED
    assert sub.confirmed_at is not None
    assert token is None


@pytest.mark.django_db
def test_resubscribe_is_idempotent(tenant, mailing_list):
    sub1, _ = subscribe(tenant=tenant, email="re@example.com", list=mailing_list)
    sub2, _ = subscribe(tenant=tenant, email="re@example.com", list=mailing_list)
    assert sub1.pk == sub2.pk
    assert Subscriber.objects.filter(tenant=tenant, email="re@example.com").count() == 1


@pytest.mark.django_db
def test_resubscribe_updates_consent_to_true(tenant, mailing_list):
    sub, _ = subscribe(tenant=tenant, email="c@example.com", list=mailing_list, consented=False)
    assert sub.consented_marketing is False
    sub, _ = subscribe(tenant=tenant, email="c@example.com", list=mailing_list, consented=True)
    assert sub.consented_marketing is True


@pytest.mark.django_db
def test_subscribe_refuses_bounced_address(tenant, mailing_list):
    sub, _ = subscribe(tenant=tenant, email="dead@example.com", list=mailing_list)
    sub.status = Subscriber.STATUS_BOUNCED
    sub.save()
    with pytest.raises(SubscriberConflict):
        subscribe(tenant=tenant, email="dead@example.com", list=mailing_list)


@pytest.mark.django_db
def test_confirm_token_flips_to_confirmed(tenant, mailing_list):
    sub, token = subscribe(
        tenant=tenant, email="conf@example.com", list=mailing_list,
    )
    assert sub.status == Subscriber.STATUS_PENDING
    confirmed = confirm_subscriber(token.token)
    assert confirmed.status == Subscriber.STATUS_CONFIRMED
    assert confirmed.confirmed_at is not None


@pytest.mark.django_db
def test_confirm_is_idempotent(tenant, mailing_list):
    sub, token = subscribe(
        tenant=tenant, email="i@example.com", list=mailing_list,
    )
    confirm_subscriber(token.token)
    # Second call must not raise.
    sub2 = confirm_subscriber(token.token)
    assert sub2.status == Subscriber.STATUS_CONFIRMED


@pytest.mark.django_db
def test_confirm_with_unknown_token_raises(db):
    with pytest.raises(UnsubscribeTokenInvalid):
        confirm_subscriber("totally-bogus-token")


@pytest.mark.django_db
def test_empty_email_raises(tenant, mailing_list):
    with pytest.raises(SubscriberConflict):
        subscribe(tenant=tenant, email="", list=mailing_list)


@pytest.mark.django_db
def test_tenant_isolation_same_email(tenant, other_tenant, mailing_list):
    """Same email under two tenants creates two distinct subscriber rows."""
    sub_a, _ = subscribe(tenant=tenant, email="shared@example.com", list=mailing_list)
    other_list = mailing_list  # same list, but it belongs to `tenant` — fine, we won't add to it
    sub_b, _ = subscribe(tenant=other_tenant, email="shared@example.com")
    assert sub_a.pk != sub_b.pk
