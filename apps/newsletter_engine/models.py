"""Newsletter engine models — Subscriber, MailingList, Membership, Tag,
Segment, Campaign, Delivery, LinkClick, Automation, AutomationStep,
AutomationEnrollment, UnsubscribeToken, BounceEvent.

Multi-tenancy
-------------
Every "user-owned" row carries ``tenant`` — a FK to the model identified by
``NEWSLETTER_TENANT_MODEL`` (defaults to ``AUTH_USER_MODEL``). The view layer
is responsible for setting ``tenant=request.user`` (or
``request.organization``, depending on your resolver — see
``NEWSLETTER_TENANT_RESOLVER`` in SETTINGS.md).

The abstract ``TenantScopedModel`` declares the FK in one place so all
concrete models stay readable.

Idempotency
-----------
Several models carry uniqueness constraints that double as idempotency keys:

- ``Subscriber(tenant, email)`` — re-subscribe with same email is an UPDATE,
  never a duplicate.
- ``Membership(subscriber, list)`` — one row per (sub, list) regardless of
  resubscribe history; status flips.
- ``Delivery(campaign, subscriber)`` — campaign fan-out is replay-safe.
- ``AutomationEnrollment(automation, subscriber)`` — same subscriber re-enrolled
  in same automation is a no-op (unless previous enrollment is cancelled).

Why ``status`` strings instead of FK to a Status model?
The set of states is small and rarely changes per project. CharField + choices
keeps lookups cheap and admin filters trivial.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


# ---------------------------------------------------------------------------
# Configurable settings helpers
# ---------------------------------------------------------------------------
def _tenant_model() -> str:
    """Dotted path of the tenant model — used as the FK target.

    Defaults to ``AUTH_USER_MODEL``: in single-user projects the tenant IS
    the user. In multi-tenant SaaS projects, set
    ``NEWSLETTER_TENANT_MODEL = "myapp.Organization"`` and provide a
    ``NEWSLETTER_TENANT_RESOLVER`` so views can pick the right tenant.
    """
    return getattr(settings, "NEWSLETTER_TENANT_MODEL", settings.AUTH_USER_MODEL)


DEFAULT_AUTOMATION_TRIGGERS: list[tuple[str, str]] = [
    ("signup",          "On subscriber signup"),
    ("list_joined",     "When subscriber joins a list"),
    ("tag_added",       "When a tag is applied"),
    ("manual",          "Manual enrollment (admin/API)"),
    ("anniversary",     "Anniversary (yearly)"),
]


def _automation_triggers() -> list[tuple[str, str]]:
    return list(getattr(
        settings, "NEWSLETTER_AUTOMATION_TRIGGERS", DEFAULT_AUTOMATION_TRIGGERS,
    ))


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------
class TenantScopedModel(models.Model):
    """Abstract mixin for any model that belongs to a tenant.

    Concrete models declare their own ``related_name`` on the tenant FK by
    overriding the field — we don't centralize ``related_name`` here because
    Django doesn't allow that pattern on abstract FKs.
    """

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# Subscribers
# ---------------------------------------------------------------------------
class Subscriber(models.Model):
    """One subscriber per (tenant, email).

    Subscribers exist regardless of which lists they're on — the relationship
    is via ``Membership`` so a single person on five lists is still one
    ``Subscriber`` row with one set of preferences, one consent record, and
    one bounce history.

    Status semantics:
      - ``pending``     — opted in but hasn't confirmed (double opt-in)
      - ``confirmed``   — fully active, will receive sends
      - ``unsubscribed`` — opted out (all-lists)
      - ``bounced``     — hard-bounced; suppressed from all sends
      - ``complained``  — marked as spam; suppressed from all sends
    """

    STATUS_PENDING = "pending"
    STATUS_CONFIRMED = "confirmed"
    STATUS_UNSUBSCRIBED = "unsubscribed"
    STATUS_BOUNCED = "bounced"
    STATUS_COMPLAINED = "complained"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending confirmation"),
        (STATUS_CONFIRMED, "Confirmed"),
        (STATUS_UNSUBSCRIBED, "Unsubscribed"),
        (STATUS_BOUNCED, "Bounced (hard)"),
        (STATUS_COMPLAINED, "Spam complaint"),
    )

    tenant = models.ForeignKey(
        _tenant_model(),
        on_delete=models.CASCADE,
        related_name="newsletter_subscribers",
    )
    email = models.EmailField(db_index=True)
    name = models.CharField(max_length=120, blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    unsubscribed_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="Where this subscription came from: 'signup', 'import', 'api', etc.",
    )
    consented_marketing = models.BooleanField(
        default=False,
        help_text=(
            "Loi 25 / RGPD: explicit opt-in to receive marketing emails. "
            "Without this, only transactional emails can be sent."
        ),
    )
    locale = models.CharField(max_length=10, default="fr")
    metadata = models.JSONField(default=dict, blank=True)
    bounce_count = models.PositiveIntegerField(default=0)
    last_bounce_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "newsletter_subscriber"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "email"),
                name="newsletter_unique_subscriber_per_tenant",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "email"]),
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.email} [{self.status}]"

    @property
    def is_sendable(self) -> bool:
        """True only if we can legally send this subscriber an email right now."""
        return self.status == self.STATUS_CONFIRMED


# ---------------------------------------------------------------------------
# Mailing lists + memberships
# ---------------------------------------------------------------------------
class MailingList(models.Model):
    """One mailing list per (tenant, slug).

    A subscriber joins a list via ``Membership``. Lists can require double
    opt-in (default) or be opt-in-only-by-trusted-source (e.g. when you
    import a confirmed list from another provider).
    """

    tenant = models.ForeignKey(
        _tenant_model(),
        on_delete=models.CASCADE,
        related_name="newsletter_lists",
    )
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=80)
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    default_from_role = models.CharField(
        max_length=32,
        default="newsletter",
        help_text=(
            "Pairs with notifications-multichannel role-based senders "
            "(e.g. 'newsletter'). Used by send_campaign when the campaign "
            "itself doesn't override."
        ),
    )
    default_reply_to = models.EmailField(blank=True, default="")
    requires_double_opt_in = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "newsletter_list"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "slug"),
                name="newsletter_unique_list_slug_per_tenant",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "slug"]),
        ]

    def __str__(self) -> str:
        return self.name


class Membership(models.Model):
    """Subscriber <-> MailingList join row.

    Status:
      - ``active``        — receiving sends targeted at this list
      - ``unsubscribed``  — opted out of THIS list only (subscriber still
        active globally for other lists)
    """

    STATUS_ACTIVE = "active"
    STATUS_UNSUBSCRIBED = "unsubscribed"
    STATUS_CHOICES = (
        (STATUS_ACTIVE, "Active"),
        (STATUS_UNSUBSCRIBED, "Unsubscribed"),
    )

    subscriber = models.ForeignKey(
        Subscriber, on_delete=models.CASCADE, related_name="memberships",
    )
    list = models.ForeignKey(
        MailingList, on_delete=models.CASCADE, related_name="memberships",
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE, db_index=True,
    )
    subscribed_at = models.DateTimeField(auto_now_add=True)
    unsubscribed_at = models.DateTimeField(null=True, blank=True)
    unsubscribe_reason = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        db_table = "newsletter_membership"
        ordering = ("-subscribed_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("subscriber", "list"),
                name="newsletter_unique_membership",
            ),
        ]
        indexes = [
            models.Index(fields=["list", "status"]),
            models.Index(fields=["subscriber", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.subscriber.email} -> {self.list.slug} [{self.status}]"


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------
class Tag(models.Model):
    """Free-form tag scoped to a tenant.

    Tags are attached to subscribers via the ``SubscriberTag`` through model.
    They feed the Segment DSL via the ``has_tag`` op.
    """

    tenant = models.ForeignKey(
        _tenant_model(),
        on_delete=models.CASCADE,
        related_name="newsletter_tags",
    )
    name = models.CharField(max_length=80)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "newsletter_tag"
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "name"),
                name="newsletter_unique_tag_per_tenant",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class SubscriberTag(models.Model):
    """M2M-through between Subscriber and Tag (explicit so we can timestamp)."""

    subscriber = models.ForeignKey(
        Subscriber, on_delete=models.CASCADE, related_name="subscriber_tags",
    )
    tag = models.ForeignKey(
        Tag, on_delete=models.CASCADE, related_name="subscriber_tags",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "newsletter_subscriber_tag"
        constraints = [
            models.UniqueConstraint(
                fields=("subscriber", "tag"),
                name="newsletter_unique_subscriber_tag",
            ),
        ]
        indexes = [
            models.Index(fields=["tag", "subscriber"]),
        ]

    def __str__(self) -> str:
        return f"{self.subscriber.email} #{self.tag.name}"


# ---------------------------------------------------------------------------
# Segments
# ---------------------------------------------------------------------------
class Segment(models.Model):
    """A saved segment — a DSL filter that resolves to a subscriber queryset.

    ``filters`` is a tree of nodes evaluated by ``segment_dsl.compile_to_q``.
    See ``segment_dsl.py`` for the supported node schema.

    A segment may be scoped to a single list (``list`` non-null) so it
    represents "active subscribers in this list matching X" — or it may be
    global (``list`` null) and span all the tenant's subscribers.
    """

    tenant = models.ForeignKey(
        _tenant_model(),
        on_delete=models.CASCADE,
        related_name="newsletter_segments",
    )
    name = models.CharField(max_length=120)
    list = models.ForeignKey(
        MailingList,
        on_delete=models.CASCADE,
        related_name="segments",
        null=True,
        blank=True,
        help_text="Optional. When set, segment evaluates within this list only.",
    )
    filters = models.JSONField(
        default=dict,
        blank=True,
        help_text="DSL tree — see segment_dsl.py for the schema.",
    )
    subscriber_count = models.PositiveIntegerField(
        default=0,
        help_text="Cached count from last evaluation. Refreshed on save() and "
                  "by selectors.cache_segment_count().",
    )
    last_evaluated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "newsletter_segment"
        ordering = ("-updated_at",)
        indexes = [
            models.Index(fields=["tenant", "-updated_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.subscriber_count} subs)"


# ---------------------------------------------------------------------------
# Campaigns + deliveries
# ---------------------------------------------------------------------------
class Campaign(models.Model):
    """One newsletter send.

    Targets EITHER a ``list`` OR a ``segment`` — never both. Enforced at the
    DB level via a check constraint. The fan-out task
    (``tasks.fan_out_campaign``) materializes one ``Delivery`` row per
    matching active subscriber, then batches the actual SMTP sends.

    Status state machine:
        draft -> scheduled -> sending -> sent
                                     \-> failed
                              \-> cancelled
    """

    STATUS_DRAFT = "draft"
    STATUS_SCHEDULED = "scheduled"
    STATUS_SENDING = "sending"
    STATUS_SENT = "sent"
    STATUS_CANCELLED = "cancelled"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = (
        (STATUS_DRAFT, "Draft"),
        (STATUS_SCHEDULED, "Scheduled"),
        (STATUS_SENDING, "Sending"),
        (STATUS_SENT, "Sent"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_FAILED, "Failed"),
    )

    tenant = models.ForeignKey(
        _tenant_model(),
        on_delete=models.CASCADE,
        related_name="newsletter_campaigns",
    )
    list = models.ForeignKey(
        MailingList,
        on_delete=models.PROTECT,
        related_name="campaigns",
        null=True,
        blank=True,
    )
    segment = models.ForeignKey(
        Segment,
        on_delete=models.PROTECT,
        related_name="campaigns",
        null=True,
        blank=True,
    )

    subject = models.CharField(max_length=255)
    html_body = models.TextField()
    text_body = models.TextField(
        blank=True,
        default="",
        help_text="Plain-text fallback. Highly recommended for deliverability.",
    )

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES,
        default=STATUS_DRAFT, db_index=True,
    )
    scheduled_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    from_role = models.CharField(
        max_length=32, blank=True, default="",
        help_text="Override the list's default_from_role. Resolved by the email backend.",
    )
    from_email_override = models.EmailField(blank=True, default="")
    reply_to = models.EmailField(blank=True, default="")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="newsletter_campaigns_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    # Stats — incremented atomically as Delivery rows progress.
    sent_count = models.PositiveIntegerField(default=0)
    delivered_count = models.PositiveIntegerField(default=0)
    open_count = models.PositiveIntegerField(default=0)
    click_count = models.PositiveIntegerField(default=0)
    bounce_count = models.PositiveIntegerField(default=0)
    unsubscribe_count = models.PositiveIntegerField(default=0)
    complaint_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "newsletter_campaign"
        ordering = ("-created_at",)
        constraints = [
            # Exactly one of list / segment must be set.
            models.CheckConstraint(
                check=(
                    (models.Q(list__isnull=False) & models.Q(segment__isnull=True))
                    | (models.Q(list__isnull=True) & models.Q(segment__isnull=False))
                ),
                name="newsletter_campaign_list_xor_segment",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "-created_at"]),
            models.Index(fields=["status", "scheduled_at"]),
        ]

    def __str__(self) -> str:
        return f"[{self.status}] {self.subject[:60]}"


class Delivery(models.Model):
    """One row per (campaign, subscriber) — the unit of fan-out.

    Created upfront by ``fan_out_campaign`` so we can throttle batches AND
    survive worker crashes (retrying a batch sees ``status=queued`` and
    skips it). Open/click/bounce/complaint updates flip the status forward;
    we keep counters for opens and clicks because a single recipient can
    re-open or re-click many times.
    """

    STATUS_PENDING = "pending"
    STATUS_QUEUED = "queued"
    STATUS_SENT = "sent"
    STATUS_DELIVERED = "delivered"     # provider confirmed via webhook
    STATUS_OPENED = "opened"
    STATUS_CLICKED = "clicked"
    STATUS_BOUNCED = "bounced"
    STATUS_COMPLAINED = "complained"
    STATUS_FAILED = "failed"
    STATUS_SKIPPED = "skipped"         # subscriber was unsendable at send time
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_QUEUED, "Queued"),
        (STATUS_SENT, "Sent"),
        (STATUS_DELIVERED, "Delivered"),
        (STATUS_OPENED, "Opened"),
        (STATUS_CLICKED, "Clicked"),
        (STATUS_BOUNCED, "Bounced"),
        (STATUS_COMPLAINED, "Complained"),
        (STATUS_FAILED, "Failed"),
        (STATUS_SKIPPED, "Skipped"),
    )

    campaign = models.ForeignKey(
        Campaign, on_delete=models.CASCADE, related_name="deliveries",
    )
    subscriber = models.ForeignKey(
        Subscriber, on_delete=models.CASCADE, related_name="deliveries",
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES,
        default=STATUS_PENDING, db_index=True,
    )
    # Short urlsafe token used in pixel + click-redirect URLs so the delivery
    # row is identified without leaking the integer PK.
    tracking_token = models.CharField(max_length=64, unique=True, db_index=True)
    provider_message_id = models.CharField(max_length=255, blank=True, default="")

    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    open_count = models.PositiveIntegerField(default=0)
    last_opened_at = models.DateTimeField(null=True, blank=True)
    clicked_at = models.DateTimeField(null=True, blank=True)
    click_count = models.PositiveIntegerField(default=0)
    last_clicked_at = models.DateTimeField(null=True, blank=True)
    bounced_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True, default="")

    class Meta:
        db_table = "newsletter_delivery"
        ordering = ("-id",)
        constraints = [
            models.UniqueConstraint(
                fields=("campaign", "subscriber"),
                name="newsletter_unique_delivery",
            ),
        ]
        indexes = [
            models.Index(fields=["campaign", "status"]),
            models.Index(fields=["subscriber", "-id"]),
        ]

    def __str__(self) -> str:
        return f"#{self.pk} {self.subscriber_id} -> camp {self.campaign_id} [{self.status}]"


class LinkClick(models.Model):
    """Audit row for every click on a tracked link.

    ``Delivery.click_count`` is the rolled-up counter; this table is the
    detail. Useful for "which links get the most engagement?" reports.
    """

    delivery = models.ForeignKey(
        Delivery, on_delete=models.CASCADE, related_name="link_clicks",
    )
    original_url = models.URLField(max_length=2000)
    clicked_at = models.DateTimeField(auto_now_add=True)
    user_agent = models.CharField(max_length=400, blank=True, default="")
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = "newsletter_link_click"
        ordering = ("-clicked_at",)
        indexes = [
            models.Index(fields=["delivery", "-clicked_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.delivery_id} -> {self.original_url[:60]}"


# ---------------------------------------------------------------------------
# Automations (drip funnels)
# ---------------------------------------------------------------------------
class Automation(models.Model):
    """A named drip automation owned by a tenant.

    ``trigger`` declares WHEN to enroll subscribers. ``trigger_config`` carries
    extra parameters per trigger (e.g. ``{"list_id": 3}`` for ``list_joined``).
    Steps fire in ``order`` with delays relative to the previous step.

    Subscribers are enrolled via ``services.automations.handle_trigger`` (auto)
    or ``services.automations.enroll_subscriber`` (manual).
    """

    tenant = models.ForeignKey(
        _tenant_model(),
        on_delete=models.CASCADE,
        related_name="newsletter_automations",
    )
    name = models.CharField(max_length=120)
    trigger = models.CharField(
        max_length=40,
        choices=_automation_triggers(),
        default="manual",
    )
    trigger_config = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "newsletter_automation"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["tenant", "trigger", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} [{self.trigger}]"


class AutomationStep(models.Model):
    """One step inside an automation.

    ``delay_seconds`` is relative to the previous step (or to enrollment time
    for the first step). The condition is the same DSL as Segment; if it
    evaluates to False at execution time, the step is skipped (but the
    enrollment still advances to the next step).
    """

    automation = models.ForeignKey(
        Automation, on_delete=models.CASCADE, related_name="steps",
    )
    order = models.PositiveIntegerField()
    delay_seconds = models.PositiveIntegerField(
        default=0,
        help_text="Wait this many seconds after the previous step (or after "
                  "enrollment for step 0) before firing.",
    )
    subject = models.CharField(max_length=255)
    html_body = models.TextField()
    text_body = models.TextField(blank=True, default="")
    condition = models.JSONField(
        default=dict,
        blank=True,
        help_text="Optional Segment-DSL tree. Empty dict = always fire.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "newsletter_automation_step"
        ordering = ("automation", "order")
        constraints = [
            models.UniqueConstraint(
                fields=("automation", "order"),
                name="newsletter_unique_step_order",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.automation.name} #{self.order} — {self.subject[:40]}"


class AutomationEnrollment(models.Model):
    """One subscriber's progress through one automation.

    ``last_step_index`` tracks the last step that COMPLETED. When NULL/-1 the
    enrollment hasn't fired its first step yet. ``last_step_at`` + the next
    step's ``delay_seconds`` give the "next due" timestamp.

    Re-enrolling the same subscriber is a no-op when there's an active
    (non-cancelled, non-completed) enrollment — see services.enroll_subscriber.
    """

    automation = models.ForeignKey(
        Automation, on_delete=models.CASCADE, related_name="enrollments",
    )
    subscriber = models.ForeignKey(
        Subscriber, on_delete=models.CASCADE, related_name="automation_enrollments",
    )
    started_at = models.DateTimeField(auto_now_add=True)
    last_step_index = models.IntegerField(
        default=-1,
        help_text="-1 = no step fired yet. Otherwise the order of the last completed step.",
    )
    last_step_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        db_table = "newsletter_automation_enrollment"
        ordering = ("-started_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("automation", "subscriber"),
                name="newsletter_unique_enrollment",
            ),
        ]
        indexes = [
            models.Index(fields=["automation", "completed_at", "cancelled_at"]),
            models.Index(fields=["last_step_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.subscriber.email} @ {self.automation.name} (step {self.last_step_index})"

    @property
    def is_active(self) -> bool:
        return self.completed_at is None and self.cancelled_at is None


# ---------------------------------------------------------------------------
# Tokens (unsubscribe + confirmation)
# ---------------------------------------------------------------------------
class UnsubscribeToken(models.Model):
    """Opaque, urlsafe token that authorizes a one-click unsubscribe OR
    confirms a double-opt-in subscription.

    Scope semantics:
      - ``"all"``              — unsubscribe globally (sets Subscriber.status=unsubscribed)
      - ``"confirm"``          — flips Subscriber.status from pending->confirmed
      - ``"list:<slug>"``      — unsubscribe from one list only
      - ``"campaign:<id>"``    — suppress the recipient for one campaign

    Tokens are single-use by default — used_at gets stamped when applied — but
    the services layer treats "already used with the same intent" as a no-op
    rather than an error (idempotent unsubscribe URLs).
    """

    subscriber = models.ForeignKey(
        Subscriber, on_delete=models.CASCADE, related_name="unsubscribe_tokens",
    )
    token = models.CharField(max_length=96, unique=True, db_index=True)
    scope = models.CharField(max_length=120, default="all")
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "newsletter_unsubscribe_token"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["subscriber", "scope"]),
        ]

    def __str__(self) -> str:
        return f"{self.subscriber.email} scope={self.scope}"


# ---------------------------------------------------------------------------
# Bounce audit
# ---------------------------------------------------------------------------
class BounceEvent(models.Model):
    """Raw bounce/complaint payloads from Resend (or another ESP).

    We keep these forever for compliance proof: if a regulator asks "why did
    you stop sending to user@example.com?", the BounceEvent row is the
    receipt. The structured ``Subscriber.status`` field is derived from the
    aggregate of these events.
    """

    KIND_HARD = "hard"
    KIND_SOFT = "soft"
    KIND_COMPLAINT = "complaint"
    KIND_UNSUB_WEBHOOK = "unsubscribe_webhook"
    KIND_CHOICES = (
        (KIND_HARD, "Hard bounce"),
        (KIND_SOFT, "Soft bounce"),
        (KIND_COMPLAINT, "Spam complaint"),
        (KIND_UNSUB_WEBHOOK, "Unsubscribe (provider webhook)"),
    )

    subscriber = models.ForeignKey(
        Subscriber, on_delete=models.CASCADE, related_name="bounce_events",
    )
    kind = models.CharField(max_length=32, choices=KIND_CHOICES, db_index=True)
    provider_message_id = models.CharField(max_length=255, blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "newsletter_bounce_event"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["subscriber", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.subscriber.email} {self.kind} @ {self.created_at:%Y-%m-%d}"
