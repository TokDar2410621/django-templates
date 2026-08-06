"""Tests for the unsubscribe flow + scopes."""
from __future__ import annotations

import pytest

from newsletter_engine.exceptions import UnsubscribeTokenInvalid
from newsletter_engine.models import Membership, Subscriber
from newsletter_engine.services.subscribers import (
    add_to_list,
    create_unsubscribe_token,
    unsubscribe,
)


@pytest.mark.django_db
def test_unsubscribe_all_flips_status_and_memberships(
    confirmed_subscriber, mailing_list,
):
    add_to_list(confirmed_subscriber, mailing_list)
    tok = create_unsubscribe_token(confirmed_subscriber, scope="all")

    sub = unsubscribe(tok.token)
    assert sub.status == Subscriber.STATUS_UNSUBSCRIBED
    m = Membership.objects.get(subscriber=confirmed_subscriber, list=mailing_list)
    assert m.status == Membership.STATUS_UNSUBSCRIBED


@pytest.mark.django_db
def test_unsubscribe_list_scope_leaves_global_status_unchanged(
    confirmed_subscriber, mailing_list, open_list,
):
    add_to_list(confirmed_subscriber, mailing_list)
    add_to_list(confirmed_subscriber, open_list)
    tok = create_unsubscribe_token(
        confirmed_subscriber, scope=f"list:{mailing_list.slug}",
    )

    sub = unsubscribe(tok.token)
    assert sub.status == Subscriber.STATUS_CONFIRMED  # global still active
    weekly = Membership.objects.get(subscriber=sub, list=mailing_list)
    other = Membership.objects.get(subscriber=sub, list=open_list)
    assert weekly.status == Membership.STATUS_UNSUBSCRIBED
    assert other.status == Membership.STATUS_ACTIVE


@pytest.mark.django_db
def test_unsubscribe_with_unknown_token_raises(db):
    with pytest.raises(UnsubscribeTokenInvalid):
        unsubscribe("nope")


@pytest.mark.django_db
def test_unsubscribe_is_idempotent(confirmed_subscriber):
    tok = create_unsubscribe_token(confirmed_subscriber, scope="all")
    unsubscribe(tok.token)
    # Second call must not raise.
    sub2 = unsubscribe(tok.token)
    assert sub2.status == Subscriber.STATUS_UNSUBSCRIBED
