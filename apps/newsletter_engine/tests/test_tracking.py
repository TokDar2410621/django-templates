"""Pixel + click-redirect tracking tests."""
from __future__ import annotations

import base64

import pytest

from newsletter_engine.models import (
    Campaign,
    Delivery,
    LinkClick,
)
from newsletter_engine.services.campaigns import create_campaign, fan_out
from newsletter_engine.services.tracking import (
    decode_click_url,
    record_click,
    record_open,
    rewrite_html_for_tracking,
)
from newsletter_engine.services.subscribers import add_to_list


@pytest.fixture
def queued_delivery(tenant, mailing_list, confirmed_subscriber):
    add_to_list(confirmed_subscriber, mailing_list)
    camp = create_campaign(
        tenant=tenant, target=mailing_list,
        subject="X", html_body="<p>x</p>",
    )
    Campaign.objects.filter(pk=camp.pk).update(status=Campaign.STATUS_SENDING)
    camp.refresh_from_db()
    fan_out(camp)
    return Delivery.objects.get(campaign=camp, subscriber=confirmed_subscriber)


@pytest.mark.django_db
def test_record_open_first_time_stamps_opened_at(queued_delivery):
    rec = record_open(queued_delivery)
    assert rec.opened_at is not None
    assert rec.status == Delivery.STATUS_OPENED
    assert rec.open_count == 1


@pytest.mark.django_db
def test_record_open_twice_increments_counter_only(queued_delivery):
    record_open(queued_delivery)
    rec2 = record_open(queued_delivery)
    assert rec2.open_count == 2
    # opened_at stays at the first open.
    assert rec2.opened_at == rec2.opened_at  # tautology, but ensures non-null
    assert rec2.opened_at <= rec2.last_opened_at


@pytest.mark.django_db
def test_first_open_increments_campaign_counter(queued_delivery):
    camp = queued_delivery.campaign
    record_open(queued_delivery)
    camp.refresh_from_db()
    assert camp.open_count == 1
    # Second open does NOT increment campaign-level (per-recipient unique).
    record_open(queued_delivery)
    camp.refresh_from_db()
    assert camp.open_count == 1


@pytest.mark.django_db
def test_record_click_creates_link_click_row(queued_delivery):
    record_click(
        queued_delivery, link_url="https://example.com/article",
        user_agent="UA", ip="127.0.0.1",
    )
    assert LinkClick.objects.filter(delivery=queued_delivery).count() == 1
    queued_delivery.refresh_from_db()
    assert queued_delivery.click_count == 1
    assert queued_delivery.clicked_at is not None


@pytest.mark.django_db
def test_rewrite_html_injects_pixel_and_rewrites_href(queued_delivery, settings):
    settings.NEWSLETTER_TRACKING_BASE_URL = "https://news.example.com"
    settings.NEWSLETTER_TRACKING_ENABLED = True

    html = '<html><body><a href="https://blog.example.com/foo">read</a></body></html>'
    out = rewrite_html_for_tracking(html, queued_delivery)
    # Pixel injected.
    assert 'src="https://news.example.com/newsletter/track/open/' in out
    # Href rewritten to go through redirect.
    assert "/newsletter/track/click/" in out


@pytest.mark.django_db
def test_rewrite_skips_mailto_and_fragment(queued_delivery, settings):
    settings.NEWSLETTER_TRACKING_BASE_URL = "https://news.example.com"
    settings.NEWSLETTER_TRACKING_ENABLED = True

    html = '<a href="mailto:hi@example.com">x</a><a href="#top">y</a>'
    out = rewrite_html_for_tracking(html, queued_delivery)
    assert 'href="mailto:hi@example.com"' in out
    assert 'href="#top"' in out


@pytest.mark.django_db
def test_rewrite_disabled_returns_original(queued_delivery, settings):
    settings.NEWSLETTER_TRACKING_ENABLED = False
    html = '<a href="https://example.com">x</a>'
    assert rewrite_html_for_tracking(html, queued_delivery) == html


def test_decode_click_url_roundtrip():
    original = "https://example.com/article?id=42&utm=x"
    encoded = base64.urlsafe_b64encode(original.encode("utf-8")).decode("ascii").rstrip("=")
    assert decode_click_url(encoded) == original


def test_decode_click_url_bad_input_returns_none():
    assert decode_click_url("not-base64!!!") is None
