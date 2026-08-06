"""Shared pytest fixtures for newsletter_engine tests.

The tests assume the project's settings declare::

    INSTALLED_APPS = [
        ...,
        "newsletter_engine",
    ]
    NEWSLETTER_EMAIL_BACKEND = "newsletter_engine.backends.dummy.DummyBackend"

We also reset the DummyBackend outbox between tests so assertions don't
cross-contaminate.
"""
from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from newsletter_engine.backends.dummy import DummyBackend
from newsletter_engine.models import (
    Automation,
    AutomationStep,
    MailingList,
    Segment,
    Subscriber,
    Tag,
)


@pytest.fixture(autouse=True)
def _use_dummy_backend(settings):
    """Force every test to use the in-memory DummyBackend.

    Also resets the outbox so per-test assertions stay isolated, and clears
    the cached backend singleton so a freshly-imported test picks up the
    setting override.
    """
    settings.NEWSLETTER_EMAIL_BACKEND = (
        "newsletter_engine.backends.dummy.DummyBackend"
    )
    DummyBackend.reset()
    # Bust the cached backend singleton so get_email_backend() re-resolves.
    from newsletter_engine import backends as backends_mod
    backends_mod._cached_backend = None
    yield
    DummyBackend.reset()


@pytest.fixture
def tenant(db):
    """A tenant — defaults to a User in this template (matches the default
    NEWSLETTER_TENANT_MODEL == AUTH_USER_MODEL).
    """
    User = get_user_model()
    return User.objects.create_user(
        username="tenantowner",
        email="tenantowner@example.com",
        password="pwpwpwpw",
    )


@pytest.fixture
def other_tenant(db):
    User = get_user_model()
    return User.objects.create_user(
        username="otherowner",
        email="otherowner@example.com",
        password="pwpwpwpw",
    )


@pytest.fixture
def mailing_list(db, tenant) -> MailingList:
    return MailingList.objects.create(
        tenant=tenant,
        name="Weekly digest",
        slug="weekly",
        requires_double_opt_in=True,
    )


@pytest.fixture
def open_list(db, tenant) -> MailingList:
    """A list that does NOT require double opt-in (immediate confirm)."""
    return MailingList.objects.create(
        tenant=tenant,
        name="Imported list",
        slug="imported",
        requires_double_opt_in=False,
    )


@pytest.fixture
def subscriber(db, tenant) -> Subscriber:
    return Subscriber.objects.create(
        tenant=tenant,
        email="alice@example.com",
        name="Alice",
        status=Subscriber.STATUS_CONFIRMED,
        consented_marketing=True,
    )


@pytest.fixture
def pending_subscriber(db, tenant) -> Subscriber:
    return Subscriber.objects.create(
        tenant=tenant,
        email="bob@example.com",
        status=Subscriber.STATUS_PENDING,
    )


@pytest.fixture
def confirmed_subscriber(subscriber) -> Subscriber:
    """Alias — keeps test names readable."""
    return subscriber


@pytest.fixture
def vip_tag(db, tenant) -> Tag:
    return Tag.objects.create(tenant=tenant, name="VIP")


@pytest.fixture
def empty_segment(db, tenant) -> Segment:
    return Segment.objects.create(
        tenant=tenant,
        name="All confirmed",
        filters={},
    )


@pytest.fixture
def manual_automation(db, tenant) -> Automation:
    auto = Automation.objects.create(
        tenant=tenant,
        name="Welcome funnel",
        trigger="manual",
        is_active=True,
    )
    AutomationStep.objects.create(
        automation=auto,
        order=0,
        delay_seconds=0,
        subject="Welcome!",
        html_body="<p>Welcome aboard.</p>",
    )
    AutomationStep.objects.create(
        automation=auto,
        order=1,
        delay_seconds=60,
        subject="Day 2: tips",
        html_body="<p>Some tips.</p>",
    )
    return auto
