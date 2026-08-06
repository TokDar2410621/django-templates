"""Activation batches + codes — pre-allocated physical QR tags.

Distribution flow:

    1. Admin creates an :class:`ActivationBatch` (size N, kind, partner_label).
    2. Server bulk-generates N :class:`ActivationCode` rows, each with:
         - a unique ``qr_slug`` (pre-allocated, NOT yet linked to a domain
           object — see :attr:`ActivationCode.linked_object_type` /
           :attr:`linked_object_id`)
         - a unique ``activation_code`` (length :data:`ACTIVATION_CODE_LENGTH`,
           default 6 digits) — empty string for PHOTO-mode batches
       Codes export to CSV for the partner/operator.
    3. Tags are physically produced with the qr_slug encoded in the QR.
       The activation_code is delivered separately (scratch-off carton for
       B2C, CSV file for B2B). PHOTO-mode tags ship without a code.
    4. Customer scans the QR → ``GET /q/<slug>/`` returns "not activated"
       state → customer enters the code in the app → ``POST /api/activation/claim/``
       → a domain object (caller-provided) is linked. The ActivationCode
       is marked consumed; that (slug, code) pair can never be reused.

Why pre-allocate the qr_slug at batch creation? Because the physical tag
has the QR baked in — once printed, the slug is immutable. If we waited
for activation to mint the slug, we'd have to print it later (impossible
for a sticker that's already on the object).

Why a GenericForeignKey for ``linked_object``? Different projects link
the claim to different domain objects — "Item" in find-it-now, "Sticker"
or "Garment" in a merch store, "AssetTag" in an inventory system. Rather
than hardcode the target model and force every project to mash its data
into our shape, we let the caller pass any model instance and we store a
weak reference (ContentType + pk). The caller can still expose a stronger
typed accessor in their own code via ``code.linked_object`` if they wish.

If you only ever link to ONE model, set the optional
:setting:`ACTIVATION_TARGET_MODEL` and use the typed
:meth:`ActivationCode.linked` shortcut — see SETTINGS.md.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


# ---------------------------------------------------------------------------
# Configurable choices (override in your project's settings.py)
# ---------------------------------------------------------------------------
DEFAULT_BATCH_KINDS: list[tuple[str, str]] = [
    ("b2c_retail",   "B2C — direct retail sale"),
    ("b2b_partner",  "B2B — partner (school, manufacturer, etc.)"),
    ("internal",     "Internal (test, demo, marketing)"),
]

DEFAULT_TAG_FORMATS: list[tuple[str, str]] = [
    ("sticker",   "Vinyl sticker"),
    ("patch",     "Fabric patch"),
    ("hang_tag",  "Hang tag"),
    ("keychain",  "Keychain"),
]


def _batch_kinds() -> list[tuple[str, str]]:
    return list(getattr(settings, "ACTIVATION_BATCH_KINDS", DEFAULT_BATCH_KINDS))


def _tag_formats() -> list[tuple[str, str]]:
    return list(getattr(settings, "ACTIVATION_TAG_FORMATS", DEFAULT_TAG_FORMATS))


def _provisional_hours() -> int:
    return int(getattr(settings, "ACTIVATION_PROVISIONAL_HOURS", 48))


def provisional_until_default() -> "models.DateTimeField":
    """Compute the default ``provisional_until`` based on current settings."""
    return timezone.now() + timedelta(hours=_provisional_hours())


class ClaimMode(models.TextChoices):
    """How a tag becomes owned.

    CODE: classic flow — buyer needs the N-digit code printed separately
    (scratch-off carton / sealed cardboard). Highest security. Default.

    PHOTO: for retail / factory-applied tags where no separate code can
    be distributed. First scanner uploads a photo of the object in their
    possession + creates the account; ownership is PROVISIONAL for
    :setting:`ACTIVATION_PROVISIONAL_HOURS` during which anyone else
    scanning can dispute with their own photo. No disputes after the
    window → CONFIRMED. Disputes → DISPUTED, admin review.
    """

    CODE = "code", "Code required"
    PHOTO = "photo", "Photo + dispute window"


class ClaimStatus(models.TextChoices):
    """Lifecycle of a photo-claim.

    Only relevant for ``ClaimMode.PHOTO`` batches. For ``ClaimMode.CODE``
    batches the code field on :class:`ActivationCode` is sufficient
    (consumed vs not consumed) — those rows always sit at CONFIRMED.
    """

    PROVISIONAL = "provisional", "Provisional (dispute window open)"
    CONFIRMED   = "confirmed",   "Confirmed (window closed, no dispute)"
    DISPUTED    = "disputed",    "Disputed (admin review)"


class ActivationBatch(models.Model):
    """A production batch — N physical tags produced together."""

    kind = models.CharField(
        max_length=32,
        choices=_batch_kinds(),
        db_index=True,
        help_text="Distribution channel for this batch.",
    )
    tag_format = models.CharField(
        max_length=32,
        choices=_tag_formats(),
        help_text="Physical form of the tag.",
    )
    claim_mode = models.CharField(
        max_length=8,
        choices=ClaimMode.choices,
        default=ClaimMode.CODE,
        db_index=True,
        help_text=(
            "CODE = a scratch-off carton or sealed envelope ships with each "
            "tag. PHOTO = no per-tag code; buyer claims by uploading a photo "
            "(use for supermarket / factory-applied)."
        ),
    )
    size = models.PositiveIntegerField(help_text="Number of tags in the batch.")

    # Free-form description of the partner (school name, manufacturer name)
    # or the retail SKU. Used in the admin + CSV header.
    partner_label = models.CharField(max_length=120, blank=True, default="")
    notes = models.TextField(blank=True, default="")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activation_batches",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "activation_batch"
        ordering = ("-created_at",)
        verbose_name = "Activation batch"
        verbose_name_plural = "Activation batches"

    def __str__(self) -> str:
        return f"Batch #{self.pk} — {self.size} × {self.get_tag_format_display()}"

    @property
    def consumed_count(self) -> int:
        return self.codes.filter(consumed_at__isnull=False).count()

    @property
    def remaining_count(self) -> int:
        return max(0, self.size - self.consumed_count)


class ActivationCode(models.Model):
    """One physical tag — qr_slug pre-allocated + activation_code printed.

    A code is "consumed" when it has been redeemed via
    :func:`services.claim_code` or :func:`services.photo_claim` by a
    logged-in user. After that, the code can never be reused even if the
    linked domain object is deleted.

    The ``linked_object`` GenericForeignKey is **opt-in**: code-only
    callers (where the activation flow just unlocks a feature flag on a
    user) can leave it null. Callers who link to a domain object (an Item,
    a Sticker, an AssetTag) populate it via :func:`services.claim_code`.
    """

    batch = models.ForeignKey(
        ActivationBatch,
        on_delete=models.CASCADE,
        related_name="codes",
    )

    # Pre-allocated at batch creation. Encoded in the printed QR. Length is
    # ``settings.QR_SLUG_LENGTH`` (default 8) — field stores up to 16 for
    # forward compatibility (cap on form fields, not on the column).
    qr_slug = models.CharField(max_length=16, unique=True, db_index=True)

    # Empty string for PHOTO-mode batches (no per-tag code printed).
    # Length ranges up to ``settings.ACTIVATION_CODE_LENGTH`` (default 6).
    activation_code = models.CharField(
        max_length=16, db_index=True, blank=True, default="",
    )

    consumed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    consumed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activation_codes_consumed",
        help_text="User who claimed this code.",
    )

    # GenericForeignKey link to the caller's domain object (Item, Sticker,
    # AssetTag, whatever). Optional — pure code-redemption flows leave
    # both fields null.
    linked_object_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="ContentType of the domain object linked at claim time.",
    )
    linked_object_id = models.PositiveBigIntegerField(null=True, blank=True)
    linked_object = GenericForeignKey("linked_object_type", "linked_object_id")

    # ----- Photo-claim specific (only used when batch.claim_mode == PHOTO) ---
    claim_status = models.CharField(
        max_length=12,
        choices=ClaimStatus.choices,
        default=ClaimStatus.CONFIRMED,
        db_index=True,
        help_text=(
            "Lifecycle of the claim. Only meaningful for PHOTO-mode codes. "
            "CODE-mode rows always sit at CONFIRMED."
        ),
    )
    provisional_until = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text=(
            "When the dispute window closes. Set to "
            "now + ACTIVATION_PROVISIONAL_HOURS at first photo-claim; "
            "cleared on CONFIRMED. Always null for CODE-mode codes."
        ),
    )
    proof_photo = models.ImageField(
        upload_to="activation_codes/proof/",
        null=True,
        blank=True,
        help_text="Photo uploaded by the first claimer (PHOTO mode only).",
    )

    class Meta:
        db_table = "activation_code"
        ordering = ("-consumed_at", "qr_slug")
        constraints = [
            # PARTIAL unique on (batch, activation_code) — only enforced when
            # the code is non-empty. PHOTO-mode batches leave the field blank
            # for every row, which would collide under a full unique
            # constraint. CODE-mode batches still get DB-side collision
            # protection on top of the in-app retry loop in
            # services.generate_batch.
            models.UniqueConstraint(
                fields=["batch", "activation_code"],
                condition=models.Q(activation_code__gt=""),
                name="actcode_unique_code_per_batch_when_set",
            ),
        ]
        indexes = [
            models.Index(fields=["consumed_at"]),
            models.Index(fields=["claim_status", "provisional_until"]),
        ]

    def __str__(self) -> str:
        suffix = self.activation_code or "(photo-claim)"
        return f"{self.qr_slug} / {suffix}"


class OwnershipDispute(models.Model):
    """A challenger to a PROVISIONAL photo-claim.

    Created when someone scans a tag whose :class:`ActivationCode` is in
    ``ClaimStatus.PROVISIONAL`` and uploads their own proof photo via
    ``POST /api/activation/photo-claim/``. Only exists for tags in
    ``ClaimMode.PHOTO`` — code-mode tags have no dispute window because
    possession of the code IS the proof.

    Lifecycle:
        1. Created with ``resolved_at=NULL`` when filed.
        2. Admin reviews in /admin/qr_tag_activation_batches/ownershipdispute/.
        3. Admin sets ``resolved_in_favor_of_claimer`` + ``resolved_at``.
        4. If True, the disputed code's ``consumed_by`` (and any linked
           object) is reassigned to the disputer. Manual transfer keeps a
           human in the moderation loop.
    """

    code = models.ForeignKey(
        ActivationCode,
        on_delete=models.CASCADE,
        related_name="ownership_disputes",
    )
    claimer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ownership_disputes_filed",
    )
    proof_photo = models.ImageField(upload_to="activation_codes/disputes/")
    claimer_message = models.TextField(blank=True, default="", max_length=2000)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_in_favor_of_claimer = models.BooleanField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ownership_disputes_resolved",
    )

    class Meta:
        db_table = "activation_ownership_dispute"
        ordering = ("-created_at",)
        constraints = [
            # One dispute row per (code, claimer) — prevents spam-clicking
            # the photo-claim button. Admin can still re-open manually.
            models.UniqueConstraint(
                fields=["code", "claimer"],
                name="actcode_unique_dispute_per_claimer",
            ),
        ]
        indexes = [
            models.Index(fields=["resolved_at"]),
        ]

    def __str__(self) -> str:
        return f"Dispute code={self.code_id} claimer={self.claimer_id}"
