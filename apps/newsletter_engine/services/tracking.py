"""Open + click tracking.

Open tracking
-------------
We inject a 1x1 transparent GIF whose URL embeds the Delivery's
``tracking_token``. When a recipient's mail client loads the image (most do
unless privacy-mode is on), our view calls ``record_open``.

Click tracking
--------------
We rewrite every absolute ``<a href>`` in the campaign HTML to point to our
redirect endpoint. The endpoint records the click then 302-redirects to the
original URL. We base64url-encode the original URL so the redirect path
contains no query characters that mail clients might mangle.

Both records are idempotent in the sense that a re-call advances the
counters (open_count, click_count) rather than failing. The "first opened"
timestamp is only stamped once; subsequent opens update last_opened_at.
"""
from __future__ import annotations

import base64
import logging
import re
from typing import Optional
from urllib.parse import urlparse

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from ..models import Campaign, Delivery, LinkClick

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------
def _tracking_base() -> str:
    """The public base URL of the backend, used to build pixel + click URLs.

    Required when tracking is enabled — falls back to "" and disables
    tracking gracefully if unset.
    """
    return (
        getattr(settings, "NEWSLETTER_TRACKING_BASE_URL", "")
        or getattr(settings, "FRONTEND_BASE_URL", "")
        or ""
    ).rstrip("/")


def _tracking_enabled() -> bool:
    return bool(getattr(settings, "NEWSLETTER_TRACKING_ENABLED", True))


def open_pixel_url(delivery: Delivery) -> str:
    base = _tracking_base()
    if not base:
        return ""
    return f"{base}/newsletter/track/open/{delivery.tracking_token}.gif"


def click_redirect_url(delivery: Delivery, original_url: str) -> str:
    base = _tracking_base()
    if not base:
        return original_url
    encoded = base64.urlsafe_b64encode(original_url.encode("utf-8")).decode("ascii").rstrip("=")
    return f"{base}/newsletter/track/click/{delivery.tracking_token}/?u={encoded}"


def decode_click_url(encoded: str) -> Optional[str]:
    """Reverse of click_redirect_url's ``u=`` payload. Returns None on bad input."""
    try:
        # Restore padding.
        pad = "=" * (-len(encoded) % 4)
        return base64.urlsafe_b64decode((encoded + pad).encode("ascii")).decode("utf-8")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# HTML rewriter (called before the email goes out)
# ---------------------------------------------------------------------------
# Match ``href="..."`` and ``href='...'`` — we keep it simple. Mail HTML is
# typically table-and-inline-style; a BeautifulSoup pass would be more
# robust but adds a dependency. Document the tradeoff.
_HREF_RE = re.compile(r"""href\s*=\s*(['"])([^'"]+)\1""", re.IGNORECASE)


def rewrite_html_for_tracking(html: str, delivery: Delivery) -> str:
    """Inject the open-pixel + rewrite ``href`` links to go through our redirect.

    Skips:
      * ``mailto:``, ``tel:``, ``#fragment``, ``javascript:`` URLs
      * URLs that already point at our tracking host
      * Plain anchors with no scheme (e.g. ``href="#"``)

    Tracking can be globally disabled via ``NEWSLETTER_TRACKING_ENABLED=False``.
    """
    if not _tracking_enabled() or not _tracking_base():
        return html

    base = _tracking_base()
    tracking_host = urlparse(base).netloc

    def _replace(m: "re.Match[str]") -> str:
        quote, url = m.group(1), m.group(2)
        low = url.lower().strip()
        if (
            low.startswith(("mailto:", "tel:", "javascript:", "#"))
            or not low.startswith(("http://", "https://"))
        ):
            return m.group(0)
        if urlparse(url).netloc == tracking_host:
            return m.group(0)
        rewritten = click_redirect_url(delivery, url)
        return f"href={quote}{rewritten}{quote}"

    rewritten_html = _HREF_RE.sub(_replace, html)

    pixel = open_pixel_url(delivery)
    if pixel:
        pixel_tag = (
            f'<img src="{pixel}" alt="" width="1" height="1" '
            f'style="display:none;border:0;outline:none;text-decoration:none;" />'
        )
        # Inject before </body> if present, else append.
        if "</body>" in rewritten_html.lower():
            # Case-preserving inject — find lower-case position and slice.
            idx = rewritten_html.lower().rfind("</body>")
            rewritten_html = rewritten_html[:idx] + pixel_tag + rewritten_html[idx:]
        else:
            rewritten_html += pixel_tag
    return rewritten_html


# ---------------------------------------------------------------------------
# Record open
# ---------------------------------------------------------------------------
def record_open(delivery: Delivery) -> Delivery:
    """Stamp the open + bump the counters atomically.

    Also increments ``Campaign.open_count`` on the FIRST open only — repeat
    opens from the same recipient bump ``Delivery.open_count`` but the
    campaign counter measures "unique opens" by recipient.
    """
    now = timezone.now()
    is_first = delivery.opened_at is None
    with transaction.atomic():
        update_kwargs: dict = {
            "open_count": F("open_count") + 1,
            "last_opened_at": now,
        }
        if is_first:
            update_kwargs["opened_at"] = now
            update_kwargs["status"] = Delivery.STATUS_OPENED
        Delivery.objects.filter(pk=delivery.pk).update(**update_kwargs)
        if is_first:
            Campaign.objects.filter(pk=delivery.campaign_id).update(
                open_count=F("open_count") + 1,
            )
    delivery.refresh_from_db()
    logger.debug(
        "newsletter.track.open delivery=%s first=%s",
        delivery.pk, is_first,
    )
    return delivery


# ---------------------------------------------------------------------------
# Record click
# ---------------------------------------------------------------------------
def record_click(
    delivery: Delivery,
    *,
    link_url: str,
    user_agent: str = "",
    ip: Optional[str] = None,
) -> LinkClick:
    """Persist a LinkClick + advance Delivery + Campaign counters."""
    now = timezone.now()
    is_first = delivery.clicked_at is None
    with transaction.atomic():
        lc = LinkClick.objects.create(
            delivery=delivery,
            original_url=link_url[:2000],
            user_agent=user_agent[:400],
            ip=ip,
        )
        update_kwargs: dict = {
            "click_count": F("click_count") + 1,
            "last_clicked_at": now,
        }
        if is_first:
            update_kwargs["clicked_at"] = now
            update_kwargs["status"] = Delivery.STATUS_CLICKED
        Delivery.objects.filter(pk=delivery.pk).update(**update_kwargs)
        if is_first:
            Campaign.objects.filter(pk=delivery.campaign_id).update(
                click_count=F("click_count") + 1,
            )
    logger.debug(
        "newsletter.track.click delivery=%s first=%s url=%s",
        delivery.pk, is_first, link_url[:60],
    )
    return lc
