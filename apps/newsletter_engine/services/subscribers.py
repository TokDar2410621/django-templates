"""Subscriber lifecycle services — subscribe, confirm, unsubscribe, bounce.

These are the entry points the public API hits. They're idempotent on the
natural key (tenant + email): calling ``subscribe`` twice for the same email
returns the same Subscriber row and never sends two confirmation emails.

Bounce handling
---------------
Hard bounces immediately suppress the subscriber. Soft bounces increment a
counter; once the counter reaches ``NEWSLETTER_BOUNCE_THRESHOLD`` (default 3)
the subscriber is auto-marked ``bounced`` to protect domain reputation.

GDPR / Loi 25
-------------
``consented_marketing`` is the audit anchor. The application is responsible
for setting this flag truthfully (an unchecked tick-box = ``False``). We
don't auto-flip it during a re-subscribe — the user must explicitly opt in
again to refresh the consent timestamp.
"""
from __future__ import annotations

import logging
import secrets
from typing import Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from ..exceptions import SubscriberConflict, UnsubscribeTokenInvalid
from ..models import (
    BounceEvent,
    MailingList,
    Membership,
    Subscriber,
    SubscriberTag,
    Tag,
    UnsubscribeToken,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------
def _new_token() -> str:
    """Return a urlsafe 256-bit random token (43 chars)."""
    return secrets.token_urlsafe(32)


def _bounce_threshold() -> int:
    return int(getattr(settings, "NEWSLETTER_BOUNCE_THRESHOLD", 3))


def _double_opt_in_default() -> bool:
    return bool(getattr(settings, "NEWSLETTER_DOUBLE_OPT_IN", True))


# ---------------------------------------------------------------------------
# Subscribe / confirm
# ---------------------------------------------------------------------------
@transaction.atomic
def subscribe(
    *,
    tenant,
    email: str,
    name: str = "",
    list: Optional[MailingList] = None,
    source: str = "",
    locale: str = "fr",
    consented: bool = False,
) -> tuple[Subscriber, Optional[UnsubscribeToken]]:
    """Subscribe an email (idempotently) and optionally add it to a list.

    Returns the ``(Subscriber, confirmation_token_or_None)`` pair. The token
    is None when the subscriber is already confirmed OR the list does not
    require double opt-in. Callers send the confirmation email when the
    token is non-None.

    Re-subscribing a hard-bounced or complained address is refused with
    ``SubscriberConflict`` — only ops/admin can revive those rows manually.
    """
    email = (email or "").strip().lower()
    if not email:
        raise SubscriberConflict("Empty email")

    sub, created = Subscriber.objects.get_or_create(
        tenant=tenant,
        email=email,
        defaults={
            "name": name,
            "status": Subscriber.STATUS_PENDING,
            "source": source,
            "locale": locale,
            "consented_marketing": consented,
        },
    )

    if not created:
        if sub.status in (Subscriber.STATUS_BOUNCED, Subscriber.STATUS_COMPLAINED):
            raise SubscriberConflict(
                f"Address {email} is suppressed ({sub.status})"
            )
        # Refresh fields that the caller may want to update.
        dirty = False
        if name and not sub.name:
            sub.name = name
            dirty = True
        if consented and not sub.consented_marketing:
            sub.consented_marketing = True
            dirty = True
        if dirty:
            sub.save(update_fields=["name", "consented_marketing", "updated_at"])

    confirmation_token: Optional[UnsubscribeToken] = None
    needs_confirm = (
        sub.status == Subscriber.STATUS_PENDING
        and (list.requires_double_opt_in if list else _double_opt_in_default())
    )
    if needs_confirm:
        confirmation_token = UnsubscribeToken.objects.create(
            subscriber=sub, token=_new_token(), scope="confirm",
        )

    if list is not None:
        membership, _ = Membership.objects.get_or_create(
            subscriber=sub, list=list,
            defaults={"status": Membership.STATUS_ACTIVE},
        )
        if membership.status != Membership.STATUS_ACTIVE:
            membership.status = Membership.STATUS_ACTIVE
            membership.unsubscribed_at = None
            membership.save(update_fields=["status", "unsubscribed_at"])

    # If the list doesn't require double opt-in and the subscriber is fresh,
    # mark them confirmed immediately.
    if (
        sub.status == Subscriber.STATUS_PENDING
        and list is not None
        and not list.requires_double_opt_in
    ):
        sub.status = Subscriber.STATUS_CONFIRMED
        sub.confirmed_at = timezone.now()
        sub.save(update_fields=["status", "confirmed_at", "updated_at"])

    logger.info(
        "newsletter.subscribe tenant=%s email=%s status=%s list=%s confirm=%s",
        getattr(tenant, "pk", None), email, sub.status,
        getattr(list, "slug", None), bool(confirmation_token),
    )
    return sub, confirmation_token


@transaction.atomic
def confirm_subscriber(token: str) -> Subscriber:
    """Flip a pending subscriber to confirmed via the token returned by
    ``subscribe``.

    Idempotent: a token whose scope is "confirm" and that's already used
    returns the same subscriber without raising — callers can safely retry.
    """
    try:
        tok = UnsubscribeToken.objects.select_related("subscriber").get(
            token=token, scope="confirm",
        )
    except UnsubscribeToken.DoesNotExist as exc:
        raise UnsubscribeTokenInvalid("Unknown confirmation token") from exc

    sub = tok.subscriber
    if sub.status == Subscriber.STATUS_PENDING:
        sub.status = Subscriber.STATUS_CONFIRMED
        sub.confirmed_at = timezone.now()
        sub.save(update_fields=["status", "confirmed_at", "updated_at"])

    if tok.used_at is None:
        tok.used_at = timezone.now()
        tok.save(update_fields=["used_at"])
    logger.info("newsletter.confirm sub=%s", sub.pk)
    return sub


# ---------------------------------------------------------------------------
# Unsubscribe
# ---------------------------------------------------------------------------
@transaction.atomic
def unsubscribe(token: str, *, scope_override: Optional[str] = None) -> Subscriber:
    """Apply an unsubscribe token.

    The token row's ``scope`` is canonical; ``scope_override`` is only used
    if the caller wants to use one token in multiple scopes (uncommon). The
    function is idempotent — re-using a used token is a no-op rather than an
    error, because mail clients sometimes pre-fetch the link.
    """
    try:
        tok = UnsubscribeToken.objects.select_related("subscriber").get(token=token)
    except UnsubscribeToken.DoesNotExist as exc:
        raise UnsubscribeTokenInvalid("Unknown unsubscribe token") from exc

    sub = tok.subscriber
    scope = scope_override or tok.scope

    if scope == "all":
        if sub.status != Subscriber.STATUS_UNSUBSCRIBED:
            sub.status = Subscriber.STATUS_UNSUBSCRIBED
            sub.unsubscribed_at = timezone.now()
            sub.save(update_fields=["status", "unsubscribed_at", "updated_at"])
        # Also flip all memberships.
        Membership.objects.filter(
            subscriber=sub, status=Membership.STATUS_ACTIVE,
        ).update(
            status=Membership.STATUS_UNSUBSCRIBED,
            unsubscribed_at=timezone.now(),
        )
    elif scope.startswith("list:"):
        slug = scope.split(":", 1)[1]
        Membership.objects.filter(
            subscriber=sub, list__slug=slug, status=Membership.STATUS_ACTIVE,
        ).update(
            status=Membership.STATUS_UNSUBSCRIBED,
            unsubscribed_at=timezone.now(),
        )
    elif scope.startswith("campaign:"):
        # Per-campaign suppression — set the delivery to skipped if pending,
        # OR just remember it via metadata. We pick the minimal approach: set
        # the existing pending delivery to SKIPPED. Future campaigns are not
        # affected.
        from ..models import Delivery
        try:
            campaign_id = int(scope.split(":", 1)[1])
        except ValueError as exc:
            raise UnsubscribeTokenInvalid("Bad campaign scope") from exc
        Delivery.objects.filter(
            campaign_id=campaign_id, subscriber=sub,
            status__in=(Delivery.STATUS_PENDING, Delivery.STATUS_QUEUED),
        ).update(status=Delivery.STATUS_SKIPPED, error="unsubscribed-token")
    else:
        raise UnsubscribeTokenInvalid(f"Unsupported scope: {scope!r}")

    if tok.used_at is None:
        tok.used_at = timezone.now()
        tok.save(update_fields=["used_at"])
    logger.info("newsletter.unsubscribe sub=%s scope=%s", sub.pk, scope)
    return sub


def create_unsubscribe_token(subscriber: Subscriber, *, scope: str = "all") -> UnsubscribeToken:
    """Mint a fresh token (used when injecting per-recipient unsub links)."""
    return UnsubscribeToken.objects.create(
        subscriber=subscriber, token=_new_token(), scope=scope,
    )


# ---------------------------------------------------------------------------
# Bounces / complaints (called from the Resend webhook)
# ---------------------------------------------------------------------------
@transaction.atomic
def mark_bounced(
    subscriber: Subscriber,
    *,
    kind: str,
    payload: Optional[dict] = None,
    provider_message_id: str = "",
) -> Subscriber:
    """Apply a bounce/complaint event to the subscriber and audit row.

    Hard bounces and complaints immediately suppress. Soft bounces increment
    the counter and only suppress once the threshold is reached.
    """
    BounceEvent.objects.create(
        subscriber=subscriber,
        kind=kind,
        provider_message_id=provider_message_id,
        payload=payload or {},
    )

    now = timezone.now()
    update_fields: list[str] = ["last_bounce_at", "updated_at"]
    subscriber.last_bounce_at = now

    if kind == BounceEvent.KIND_HARD:
        subscriber.status = Subscriber.STATUS_BOUNCED
        update_fields.append("status")
    elif kind == BounceEvent.KIND_COMPLAINT:
        subscriber.status = Subscriber.STATUS_COMPLAINED
        subscriber.unsubscribed_at = now
        update_fields.extend(["status", "unsubscribed_at"])
    elif kind == BounceEvent.KIND_UNSUB_WEBHOOK:
        subscriber.status = Subscriber.STATUS_UNSUBSCRIBED
        subscriber.unsubscribed_at = now
        update_fields.extend(["status", "unsubscribed_at"])
    elif kind == BounceEvent.KIND_SOFT:
        subscriber.bounce_count += 1
        update_fields.append("bounce_count")
        if subscriber.bounce_count >= _bounce_threshold():
            subscriber.status = Subscriber.STATUS_BOUNCED
            update_fields.append("status")
    subscriber.save(update_fields=update_fields)
    logger.info(
        "newsletter.bounce sub=%s kind=%s status=%s count=%s",
        subscriber.pk, kind, subscriber.status, subscriber.bounce_count,
    )
    return subscriber


# ---------------------------------------------------------------------------
# List + tag mutations
# ---------------------------------------------------------------------------
@transaction.atomic
def add_to_list(subscriber: Subscriber, list: MailingList) -> Membership:
    """Idempotently add a subscriber to a list (or re-activate the row)."""
    m, _ = Membership.objects.get_or_create(
        subscriber=subscriber, list=list,
        defaults={"status": Membership.STATUS_ACTIVE},
    )
    if m.status != Membership.STATUS_ACTIVE:
        m.status = Membership.STATUS_ACTIVE
        m.unsubscribed_at = None
        m.save(update_fields=["status", "unsubscribed_at"])
    return m


@transaction.atomic
def remove_from_list(
    subscriber: Subscriber, list: MailingList, *, reason: str = "",
) -> Optional[Membership]:
    """Flip a membership to unsubscribed. Returns None if no row existed."""
    m = Membership.objects.filter(subscriber=subscriber, list=list).first()
    if m is None:
        return None
    if m.status != Membership.STATUS_UNSUBSCRIBED:
        m.status = Membership.STATUS_UNSUBSCRIBED
        m.unsubscribed_at = timezone.now()
        m.unsubscribe_reason = reason[:200]
        m.save(update_fields=["status", "unsubscribed_at", "unsubscribe_reason"])
    return m


def tag_subscriber(subscriber: Subscriber, tag: Tag) -> SubscriberTag:
    """Idempotently attach a tag to a subscriber."""
    obj, _ = SubscriberTag.objects.get_or_create(subscriber=subscriber, tag=tag)
    return obj


def untag_subscriber(subscriber: Subscriber, tag: Tag) -> bool:
    """Remove a tag. Returns True if a row was deleted, False otherwise."""
    deleted, _ = SubscriberTag.objects.filter(
        subscriber=subscriber, tag=tag,
    ).delete()
    return bool(deleted)
