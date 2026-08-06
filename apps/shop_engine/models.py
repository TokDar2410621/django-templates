"""shop-engine models — Category, Tag, Product, ProductVariant, ProductReview,
Wishlist, WishlistItem, Cart, CartItem, Order, OrderItem, Coupon, CouponUsage,
Affiliate, AffiliateClick, AffiliateConversion, AffiliatePayout,
ProviderSyncLog.

Single-tenant
-------------
**There is no ``tenant`` FK anywhere.** This template assumes one
deployment = one shop. Multi-tenant is intentionally out of scope — the
moment you bolt a tenant FK onto Cart / Coupon / Affiliate, you need a
resolver layer in every view, and the design calls (scope of slugs,
scope of affiliate codes, scope of coupon codes — global or per-tenant?)
all become forks. If you need multi-tenant, the cleanest path is to
wrap this engine in an ``organisations`` proxy that owns one shop_engine
deployment per row.

Money
-----
All amounts are integers in the smallest currency unit (cents). Decimals
introduce rounding bugs the moment you start splitting commissions or
discounts proportionally across cart lines. The display layer formats
back to ``XX.YY`` — see ``selectors.py`` for the helpers.

Idempotency keys
----------------
Several models carry uniqueness constraints that double as idempotency
hooks:

- ``Product.slug`` — re-importing the same upstream product produces an
  UPDATE, not a duplicate.
- ``CartItem(cart, product, variant)`` — adding the same SKU twice
  increments the quantity instead of creating a second row.
- ``Order.order_number`` + ``Order.stripe_payment_intent_id`` — webhook
  replays can't double-process the same payment.
- ``CouponUsage(coupon, order)`` — one redemption per order, no matter
  how many times the user retries the apply-coupon endpoint.
- ``AffiliateConversion(affiliate, order)`` — one conversion per order.
- ``Affiliate.code`` — referral link uniqueness.

Why ``status`` strings instead of FK to a Status model?
The set of states per model is small and rarely changes per project.
``CharField + choices`` keeps lookups cheap and admin filters trivial.
The trade-off is that adding a new status requires a code change AND a
migration, which is the right friction for state machines.
"""
from __future__ import annotations

import secrets
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


# ---------------------------------------------------------------------------
# Configurable settings helpers
# ---------------------------------------------------------------------------
def _default_currency() -> str:
    return str(getattr(settings, "SHOP_DEFAULT_CURRENCY", "CAD"))


def _default_commission_bps() -> int:
    return int(getattr(settings, "SHOP_AFFILIATE_DEFAULT_COMMISSION_BPS", 1000))


def _order_number_prefix() -> str:
    return str(getattr(settings, "SHOP_ORDER_NUMBER_PREFIX", "ORD-"))


def _new_affiliate_code() -> str:
    """Return an ~8-char URL-safe affiliate code.

    ``secrets.token_urlsafe(6)`` gives 8 chars from the URL-safe alphabet
    (no ``+/`` and no ``-_`` confusion in QR codes / printed cards).
    """
    return secrets.token_urlsafe(6)


def _new_magic_link_token() -> str:
    """Cryptographically strong magic-link token for email-only affiliates."""
    return secrets.token_urlsafe(32)


def _new_order_number() -> str:
    """``ORD-2026-A8K3Q9XL`` style — prefix + year + 8 base32 chars.

    Year is informational only; uniqueness comes from the random tail
    (32^8 ≈ 1.1e12 combinations, plenty for a non-enterprise shop). We
    still set ``unique=True`` on the column so a collision would raise
    rather than silently overwrite — never observed but cheap insurance.
    """
    # base32-friendly alphabet without ambiguous I, L, O, 0, 1.
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    tail = "".join(secrets.choice(alphabet) for _ in range(8))
    return f"{_order_number_prefix()}{timezone.now():%Y}-{tail}"


# ---------------------------------------------------------------------------
# Catalogue — Category, Tag
# ---------------------------------------------------------------------------
class Category(models.Model):
    """Single-rooted category tree.

    Self-FK ``parent`` lets you express ``Vêtements / Hoodies / Manches
    longues``. The frontend usually only renders 2 levels deep; the tree
    is unbounded in storage and the helpers in ``selectors.py`` walk it.
    """

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=120, unique=True, db_index=True)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
        help_text="Parent category — leave empty for a top-level row.",
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    order = models.IntegerField(
        default=0,
        help_text="Display order — lower numbers show up first.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("order", "name")
        verbose_name = "category"
        verbose_name_plural = "categories"

    def __str__(self) -> str:
        return self.name


class Tag(models.Model):
    """Lightweight tag for product filtering (``new``, ``sale``, ``eco``)."""

    name = models.CharField(max_length=60, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


# ---------------------------------------------------------------------------
# Catalogue — Product, ProductVariant
# ---------------------------------------------------------------------------
class Product(models.Model):
    """Catalogue product.

    Provider abstraction
    --------------------
    ``provider`` + ``external_id`` together identify the upstream
    catalogue row this product was synced from. For DB-managed products
    (the ``local`` provider, the default), ``provider == "local"`` and
    ``external_id`` is blank. For Alibaba/Gelato/other-stub-driven
    products, ``provider`` is the dotted path's tail and
    ``external_id`` is the upstream ID — sync workflows use this pair to
    UPSERT.

    Images
    ------
    ``images`` is a JSONField list — either bare URL strings OR
    ``{"url": "...", "alt": "...", "is_primary": true}`` dicts. Kept as
    JSON because the storefront rarely needs to query *into* the images
    (filter by alt text, etc.) and a one-to-many ``ProductImage`` model
    is a separate axis of complexity. For a heavy gallery workflow,
    project it out into its own table later.
    """

    PROVIDER_LOCAL = "local"

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True, db_index=True)
    description = models.TextField(
        blank=True,
        help_text="Markdown supported. The frontend is expected to render.",
    )
    category = models.ForeignKey(
        Category,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="products",
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name="products")
    is_active = models.BooleanField(default=True, db_index=True)
    is_featured = models.BooleanField(
        default=False,
        help_text="Surfaced on the home page / boutique header.",
    )
    provider = models.CharField(
        max_length=50,
        default=PROVIDER_LOCAL,
        db_index=True,
        help_text="Which provider sourced this product. ``local`` = DB-managed.",
    )
    external_id = models.CharField(
        max_length=200,
        blank=True,
        db_index=True,
        help_text="Upstream provider's ID for UPSERT during sync. Blank for local products.",
    )
    base_price_cents = models.IntegerField(
        help_text=(
            "Default price in the smallest currency unit (cents). "
            "Variants can override via ``ProductVariant.price_cents``."
        ),
    )
    currency = models.CharField(
        max_length=3,
        default=_default_currency,
        help_text="ISO 4217 currency code. Mixed-currency shops are out of scope.",
    )
    images = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "List of image entries. Either bare URL strings or dicts "
            '``{"url": ..., "alt": ..., "is_primary": ...}``. See README.'
        ),
    )
    seo_title = models.CharField(max_length=200, blank=True)
    seo_description = models.CharField(max_length=320, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-is_featured", "-created_at")
        indexes = [
            models.Index(fields=["is_active", "is_featured"]),
            models.Index(fields=["provider", "external_id"]),
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def primary_image_url(self) -> str:
        """Best-guess primary image URL, or empty string if none.

        Walks ``images`` and returns the first ``is_primary=True`` dict's
        URL, or falls back to the first entry (string or dict). Used by
        order receipts + cart thumbnails so callers don't have to branch
        on the storage shape.
        """
        for entry in self.images or []:
            if isinstance(entry, dict) and entry.get("is_primary"):
                return str(entry.get("url") or "")
        for entry in self.images or []:
            if isinstance(entry, str):
                return entry
            if isinstance(entry, dict):
                return str(entry.get("url") or "")
        return ""


class ProductVariant(models.Model):
    """Sized/colored/scoped variant of a product.

    ``attributes`` is the canonical place for whatever axes the product
    actually varies on — size, color, scent, length. The frontend reads
    ``attributes`` to render its picker. ``label`` is the human-readable
    summary (e.g. ``"Large / Red"``) — DRY this from ``attributes`` if
    you ever need to.

    Inventory
    ---------
    ``track_inventory=False`` means infinite stock (digital goods,
    print-on-demand). ``track_inventory=True`` + ``stock_quantity=0`` =
    out of stock; the cart endpoints reject add-to-cart in that case.
    """

    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="variants",
    )
    sku = models.CharField(
        max_length=80,
        unique=True,
        db_index=True,
        help_text="Stock-keeping unit — visible to the operator, sometimes printed on labels.",
    )
    label = models.CharField(
        max_length=120,
        help_text='Human summary of the variant — e.g. "Large / Red".',
    )
    price_cents = models.IntegerField(
        null=True,
        blank=True,
        help_text="If set, overrides ``Product.base_price_cents`` for this variant.",
    )
    stock_quantity = models.IntegerField(
        default=0,
        help_text="Available units. Ignored when ``track_inventory`` is False.",
    )
    track_inventory = models.BooleanField(
        default=True,
        help_text="Uncheck for infinite stock (digital, print-on-demand).",
    )
    attributes = models.JSONField(
        default=dict,
        blank=True,
        help_text='Free-form attributes ``{"size": "L", "color": "red"}``.',
    )
    weight_grams = models.IntegerField(
        default=0,
        help_text="Used by shipping rate calculators. 0 = unknown.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("product", "label")
        indexes = [
            models.Index(fields=["product", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.product.title} — {self.label}"

    def effective_price_cents(self) -> int:
        """Variant override if set, otherwise product base price."""
        if self.price_cents is not None:
            return int(self.price_cents)
        return int(self.product.base_price_cents)

    def is_in_stock(self, quantity: int = 1) -> bool:
        if not self.track_inventory:
            return True
        return int(self.stock_quantity) >= int(quantity)


class ProductReview(models.Model):
    """Customer review for a product.

    ``is_verified_purchase`` is auto-flipped by a signal when the user
    has a paid Order containing the product. The flag is informational —
    moderation lives on ``is_published`` so an operator can hide an
    abusive review without losing the verification audit trail.
    """

    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="reviews",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="shop_reviews",
        help_text="Author — null if the user was deleted after posting.",
    )
    author_name_snapshot = models.CharField(
        max_length=120,
        blank=True,
        help_text="Display name captured at write time — survives user deletion.",
    )
    rating = models.PositiveSmallIntegerField(
        help_text="1 to 5 stars.",
    )
    title = models.CharField(max_length=200, blank=True)
    body = models.TextField(blank=True)
    is_verified_purchase = models.BooleanField(default=False)
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["product", "is_published"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=Q(rating__gte=1) & Q(rating__lte=5),
                name="shop_engine_review_rating_range",
            ),
        ]

    def __str__(self) -> str:
        name = self.author_name_snapshot or (str(self.user) if self.user else "Anonymous")
        return f"{name} → {self.product.title}: {self.rating}/5"


# ---------------------------------------------------------------------------
# Wishlist
# ---------------------------------------------------------------------------
class Wishlist(models.Model):
    """One wishlist per user. Auto-created on first add."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="shop_wishlist",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "wishlist"
        verbose_name_plural = "wishlists"

    def __str__(self) -> str:
        return f"Wishlist({self.user})"


class WishlistItem(models.Model):
    wishlist = models.ForeignKey(
        Wishlist, on_delete=models.CASCADE, related_name="items",
    )
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="+",
    )
    variant = models.ForeignKey(
        ProductVariant,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    notes = models.CharField(max_length=200, blank=True)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = (("wishlist", "product", "variant"),)
        ordering = ("-added_at",)

    def __str__(self) -> str:
        return f"♥ {self.product.title}"


# ---------------------------------------------------------------------------
# Cart
# ---------------------------------------------------------------------------
class Cart(models.Model):
    """Shopping cart — one active per (user OR session_key).

    Anon → user transfer
    --------------------
    When an anonymous visitor logs in mid-browse, the view layer calls
    ``services.cart.transfer_anonymous_cart_to_user`` which merges the
    session-keyed cart into the user's existing one. Without this, the
    user would lose everything they put in the cart pre-login.

    Currency snapshot
    -----------------
    ``currency`` is snapshotted on the Cart row so a price-change
    elsewhere doesn't silently shift the cart's display currency
    mid-flow. The store-level default lives in ``SHOP_DEFAULT_CURRENCY``.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="shop_carts",
    )
    session_key = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="Django session key — used for anonymous carts.",
    )
    currency = models.CharField(max_length=3, default=_default_currency)
    applied_coupon = models.ForeignKey(
        "Coupon",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="active_carts",
        help_text="Coupon currently applied to this cart (informational; re-validated at checkout).",
    )
    affiliate_code = models.CharField(
        max_length=32,
        blank=True,
        help_text=(
            "Affiliate code captured from the visitor's cookie when they "
            "started shopping. Snapshotted onto the Order at checkout."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Soft deadline for anonymous carts — past this point the daily "
            "``expire_old_carts`` Celery beat sweeps the row."
        ),
    )

    class Meta:
        constraints = [
            # One of (user, session_key) must be set. Both can be set
            # temporarily during the anonymous → user transfer window;
            # neither is never valid.
            models.CheckConstraint(
                check=Q(user__isnull=False) | ~Q(session_key=""),
                name="shop_engine_cart_owner_required",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "-updated_at"]),
            models.Index(fields=["session_key", "-updated_at"]),
        ]

    def __str__(self) -> str:
        owner = self.user or f"session:{self.session_key[:8]}..."
        return f"Cart({owner})"


class CartItem(models.Model):
    """One line in a cart.

    ``unit_price_cents`` is snapshotted at the moment of add-to-cart so
    that a price change on the catalogue side doesn't silently shift the
    cart's total. Re-validated at checkout (services.cart.calculate_totals)
    against the live variant/product price; mismatch raises a friendly
    "price changed, please review" error rather than auto-updating.
    """

    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="+")
    variant = models.ForeignKey(
        ProductVariant,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    quantity = models.PositiveIntegerField(default=1)
    unit_price_cents = models.IntegerField(
        help_text="Snapshot at add-to-cart time — re-validated at checkout.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (("cart", "product", "variant"),)
        ordering = ("created_at",)

    def __str__(self) -> str:
        suffix = f" / {self.variant.label}" if self.variant else ""
        return f"{self.product.title}{suffix} ×{self.quantity}"

    @property
    def line_total_cents(self) -> int:
        return int(self.unit_price_cents) * int(self.quantity)


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
class Order(models.Model):
    """Persisted order — the immutable record once the customer commits.

    State machine
    -------------
    Transitions are enforced by ``services.orders.transition_order``::

        draft ──► awaiting_payment ──► paid ──► fulfilling ──► shipped ──► delivered
                       │                  │                                    │
                       └─► cancelled      └─► refunded                         └─► refunded
                       │                  │
                       └─► failed         └─► cancelled

    ``draft`` exists for "compose the order before triggering Stripe" UX
    flows; you can skip it and go straight to ``awaiting_payment`` if
    you create the PaymentIntent in the same view that creates the order
    (recommended — that's what ``services.checkout.create_checkout``
    does).

    Snapshots vs FKs
    ----------------
    Most "name" / "address" / "applied code" fields are snapshotted as
    strings/JSON rather than FKs because the source rows might be
    deleted later (user wiped their account, coupon archived, affiliate
    banned) and an order MUST stay rendered intact for accounting +
    customer-support workflows.
    """

    STATUS_DRAFT = "draft"
    STATUS_AWAITING_PAYMENT = "awaiting_payment"
    STATUS_PAID = "paid"
    STATUS_FULFILLING = "fulfilling"
    STATUS_SHIPPED = "shipped"
    STATUS_DELIVERED = "delivered"
    STATUS_REFUNDED = "refunded"
    STATUS_CANCELLED = "cancelled"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_AWAITING_PAYMENT, "Awaiting payment"),
        (STATUS_PAID, "Paid"),
        (STATUS_FULFILLING, "Fulfilling"),
        (STATUS_SHIPPED, "Shipped"),
        (STATUS_DELIVERED, "Delivered"),
        (STATUS_REFUNDED, "Refunded"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_FAILED, "Payment failed"),
    ]

    #: Statuses past which a refund makes sense (charged customer money).
    PAID_STATUSES = {
        STATUS_PAID, STATUS_FULFILLING, STATUS_SHIPPED, STATUS_DELIVERED,
    }
    #: Terminal statuses (no further transitions allowed).
    TERMINAL_STATUSES = {STATUS_REFUNDED, STATUS_CANCELLED, STATUS_FAILED, STATUS_DELIVERED}

    order_number = models.CharField(
        max_length=40,
        unique=True,
        db_index=True,
        default=_new_order_number,
        help_text="Public-facing order ID. Format: ``<prefix><year>-<8 base32>``.",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="shop_orders",
        help_text="Null for guest checkout — ``email`` is the only contact.",
    )
    status = models.CharField(
        max_length=24,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
        db_index=True,
    )
    email = models.EmailField(help_text="Contact email — required for both guest and user orders.")
    billing_address = models.JSONField(
        default=dict,
        blank=True,
        help_text='Snapshot. Expected keys: ``{name, line1, line2, city, region, postal_code, country}``.',
    )
    shipping_address = models.JSONField(
        default=dict,
        blank=True,
        help_text="Same shape as ``billing_address``. Empty for digital-only orders.",
    )

    # Money breakdown (all in cents)
    subtotal_cents = models.IntegerField(default=0)
    shipping_cents = models.IntegerField(default=0)
    tax_cents = models.IntegerField(default=0)
    discount_cents = models.IntegerField(default=0)
    total_cents = models.IntegerField(default=0)
    currency = models.CharField(max_length=3, default=_default_currency)

    # Stripe linkage
    stripe_payment_intent_id = models.CharField(
        max_length=80, blank=True, db_index=True,
    )
    stripe_charge_id = models.CharField(max_length=80, blank=True)

    # Applied promo snapshots — kept as strings so deleting the Coupon /
    # Affiliate rows later doesn't erase the audit trail.
    applied_coupon_code = models.CharField(max_length=80, blank=True)
    affiliate_code = models.CharField(max_length=80, blank=True, db_index=True)

    # Provider integration (Alibaba/Gelato order IDs, tracking numbers, ...)
    provider_metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Free-form metadata written by the fulfillment provider — "
            "e.g. ``{provider: 'gelato', order_id: '...', tracking_url: ...}``."
        ),
    )

    customer_notes = models.TextField(blank=True)

    # Lifecycle timestamps
    placed_at = models.DateTimeField(null=True, blank=True, help_text="When the customer hit 'checkout'.")
    paid_at = models.DateTimeField(null=True, blank=True)
    fulfilled_at = models.DateTimeField(null=True, blank=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    refunded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["email", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.order_number} ({self.status})"

    @property
    def is_paid(self) -> bool:
        return self.status in self.PAID_STATUSES

    @property
    def is_terminal(self) -> bool:
        return self.status in self.TERMINAL_STATUSES


class OrderItem(models.Model):
    """One line in an order. Heavily snapshotted.

    Snapshot rationale: if the product or variant is deleted / renamed /
    discontinued after the order is placed, the receipt + admin still
    show "what was bought" exactly as it was at checkout time. The FKs
    survive only for join convenience (``order.items.all()`` doesn't
    need to fetch product names from snapshots); ``on_delete=SET_NULL``
    so a delete cascades cleanly.
    """

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        Product,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    variant = models.ForeignKey(
        ProductVariant,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    # Snapshots — these are the source of truth for display.
    product_title = models.CharField(max_length=200)
    variant_label = models.CharField(max_length=120, blank=True)
    sku = models.CharField(max_length=80, blank=True)
    unit_price_cents = models.IntegerField()
    quantity = models.PositiveIntegerField()
    line_total_cents = models.IntegerField()

    class Meta:
        ordering = ("pk",)

    def __str__(self) -> str:
        suffix = f" / {self.variant_label}" if self.variant_label else ""
        return f"{self.product_title}{suffix} ×{self.quantity}"


# ---------------------------------------------------------------------------
# Coupons
# ---------------------------------------------------------------------------
class Coupon(models.Model):
    """Discount coupon.

    Three kinds:

    - ``percent`` — ``value`` is a percentage 0–100; discount is
      ``floor(subtotal * value / 100)``.
    - ``fixed`` — ``value`` is an absolute amount in MAJOR currency
      units (e.g. ``Decimal("10.00")`` = 10 CAD); discount is capped at
      the subtotal so a $10 coupon on a $5 order does nothing.
    - ``free_shipping`` — zeros out ``shipping_cents`` on the order;
      ``value`` is ignored.

    Scope
    -----
    Empty ``product_scope`` M2M means "applies to every product".
    Otherwise the coupon only applies when AT LEAST ONE cart line is for
    a product in scope; the discount is then computed on the full cart
    subtotal, not on the in-scope lines only — the simplest semantics
    that consistently makes sense to a customer.
    """

    KIND_PERCENT = "percent"
    KIND_FIXED = "fixed"
    KIND_FREE_SHIPPING = "free_shipping"

    KIND_CHOICES = [
        (KIND_PERCENT, "Percent off"),
        (KIND_FIXED, "Fixed amount off"),
        (KIND_FREE_SHIPPING, "Free shipping"),
    ]

    code = models.CharField(
        max_length=80,
        unique=True,
        db_index=True,
        help_text="The string the customer types at checkout. Case-insensitive lookup.",
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text=(
            "For ``percent``: 0–100. For ``fixed``: amount in major units (e.g. 10.00 = $10). "
            "For ``free_shipping``: unused, set to 0."
        ),
    )
    max_uses = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Global cap. Null = unlimited.",
    )
    max_uses_per_user = models.PositiveIntegerField(
        default=1,
        help_text="Per-user cap. ``0`` is rejected (would make the coupon unusable).",
    )
    times_used = models.PositiveIntegerField(default=0)
    starts_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=True, blank=True)
    minimum_order_cents = models.IntegerField(
        default=0,
        help_text="Cart subtotal must be ≥ this for the coupon to apply.",
    )
    product_scope = models.ManyToManyField(
        Product,
        blank=True,
        related_name="scoped_coupons",
        help_text="Empty = applies to all products.",
    )
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        if self.kind == self.KIND_PERCENT:
            return f"{self.code} (-{self.value}%)"
        if self.kind == self.KIND_FIXED:
            return f"{self.code} (-{self.value})"
        return f"{self.code} (free shipping)"


class CouponUsage(models.Model):
    """One redemption — append-only.

    Unique on ``(coupon, order)`` so retrying the apply-coupon endpoint
    can't double-count usage. The ``times_used`` counter on ``Coupon``
    is incremented atomically when a row is inserted (see
    ``services.cart.apply_coupon``).
    """

    coupon = models.ForeignKey(Coupon, on_delete=models.CASCADE, related_name="usages")
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="coupon_usages")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Null for guest orders.",
    )
    used_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = (("coupon", "order"),)
        ordering = ("-used_at",)


# ---------------------------------------------------------------------------
# Affiliates (hybrid: user-FK OR email-only)
# ---------------------------------------------------------------------------
class Affiliate(models.Model):
    """Affiliate / referral row.

    Hybrid auth model
    -----------------
    ``user`` is **nullable**. Two flavours coexist on the same table:

    1. **User-based affiliates** — ``user`` set, ``magic_link_token``
       empty. They log into the dashboard with their normal app
       credentials (the same JWT/session as the rest of the site) and
       see their affiliate panel.

    2. **Email-only affiliates** — ``user`` null, ``email`` set,
       ``magic_link_token`` populated. Used for external partners who
       don't have (or shouldn't have) a regular account on the app —
       agencies, influencers, brands. They log in via emailed magic
       link, no password ever stored.

    Switching modes is just nulling/un-nulling ``user`` — the rest of
    the data (clicks, conversions, payouts) is unchanged.

    Commission math
    ---------------
    Per-conversion: ``floor(order.subtotal_cents * commission_bps /
    10_000) + flat_per_order_cents``. Snapshotted onto each
    ``AffiliateConversion`` so a later edit to ``commission_bps`` doesn't
    rewrite past payouts.
    """

    STATUS_PENDING = "pending"
    STATUS_ACTIVE = "active"
    STATUS_PAUSED = "paused"
    STATUS_BANNED = "banned"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending review"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_PAUSED, "Paused"),
        (STATUS_BANNED, "Banned"),
    ]

    PAYOUT_PAYPAL = "paypal"
    PAYOUT_BANK = "bank"
    PAYOUT_MANUAL = "manual"

    PAYOUT_METHODS = [
        (PAYOUT_PAYPAL, "PayPal"),
        (PAYOUT_BANK, "Bank transfer"),
        (PAYOUT_MANUAL, "Manual / other"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="shop_affiliates",
        help_text="If null, this is an email-only affiliate (magic-link auth).",
    )
    email = models.EmailField(
        help_text="Required even for user-based affiliates — used for payout receipts + magic-link delivery.",
    )
    payout_email = models.EmailField(
        blank=True,
        help_text='Optional alternate payout email (e.g. for "send payouts to my accountant").',
    )
    code = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        default=_new_affiliate_code,
        help_text="Public referral code — visible in URLs (``/r/<code>/``) and codes.",
    )
    display_name = models.CharField(max_length=120, blank=True)
    commission_bps = models.PositiveIntegerField(
        default=_default_commission_bps,
        help_text=(
            "Commission in basis points (1/100 of 1%). 1000 = 10%. "
            "Applied to ``order.subtotal_cents``."
        ),
    )
    flat_per_order_cents = models.IntegerField(
        default=0,
        help_text="Flat amount added to every conversion's commission (e.g. 200 = $2).",
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True,
    )
    payout_method = models.CharField(
        max_length=20, choices=PAYOUT_METHODS, default=PAYOUT_MANUAL,
    )
    payout_details = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            'Payout-method-specific details: ``{"paypal_email": ...}`` or '
            '``{"bank_name": ..., "iban": ..., "swift": ...}``.'
        ),
    )

    # Denormalised counters (kept in sync by services). Cheap reads on
    # the dashboard — the equivalent COUNT/SUM would be fine here too
    # but the dashboard page hits it on every refresh.
    total_clicks = models.PositiveIntegerField(default=0)
    total_conversions = models.PositiveIntegerField(default=0)
    total_paid_cents = models.IntegerField(default=0)

    # Magic-link auth (used for email-only affiliates)
    magic_link_token = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text=(
            "Long random token — sent in a one-click login URL. Regenerated "
            "via ``services.affiliates.regenerate_magic_link``. Empty for "
            "user-based affiliates (they log in normally)."
        ),
    )
    magic_link_sent_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            # At least one of (user, email) must be set. ``email`` is a
            # required field already; this is belt-and-braces in case
            # someone bypasses the model layer via raw SQL.
            models.CheckConstraint(
                check=Q(user__isnull=False) | ~Q(email=""),
                name="shop_engine_affiliate_owner_required",
            ),
        ]

    def __str__(self) -> str:
        label = self.display_name or (str(self.user) if self.user else self.email)
        return f"{label} ({self.code})"

    @property
    def is_user_based(self) -> bool:
        return self.user_id is not None

    @property
    def is_email_only(self) -> bool:
        return self.user_id is None


class AffiliateClick(models.Model):
    """One referral click — recorded by the ``/r/<code>/`` landing view.

    Used for attribution (matching a later conversion back to the click
    that brought the visitor in). We keep more than strictly necessary
    so the dashboard can show "top referring sites" — strip
    ``user_agent`` / ``referer`` if your privacy stance is stricter.
    """

    affiliate = models.ForeignKey(
        Affiliate, on_delete=models.CASCADE, related_name="clicks",
    )
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    referer = models.CharField(max_length=500, blank=True)
    landing_url = models.CharField(max_length=500, blank=True)
    session_key = models.CharField(max_length=64, blank=True)
    cookie_id = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        db_index=True,
        help_text="UUID stored in the visitor's referral cookie — used to match later conversions.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["affiliate", "-created_at"]),
            models.Index(fields=["cookie_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.affiliate.code} @ {self.created_at:%Y-%m-%d %H:%M}"


class AffiliateConversion(models.Model):
    """One paid order attributed to an affiliate.

    Snapshots ``commission_bps_applied`` + ``flat_per_order_cents_applied``
    so future tweaks to the affiliate's deal don't rewrite history.
    """

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_PAID = "paid"
    STATUS_REVERSED = "reversed"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending review"),
        (STATUS_APPROVED, "Approved (awaiting payout)"),
        (STATUS_PAID, "Paid"),
        (STATUS_REVERSED, "Reversed (refund / fraud)"),
    ]

    affiliate = models.ForeignKey(
        Affiliate, on_delete=models.CASCADE, related_name="conversions",
    )
    order = models.OneToOneField(
        Order, on_delete=models.CASCADE, related_name="affiliate_conversion",
    )
    click = models.ForeignKey(
        AffiliateClick,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="conversions",
        help_text="The click that brought the visitor in. Null if attribution failed.",
    )

    gross_cents = models.IntegerField(
        help_text="Order subtotal at conversion time (snapshot).",
    )
    commission_bps_applied = models.PositiveIntegerField(
        help_text="Snapshot of ``Affiliate.commission_bps`` at conversion time.",
    )
    flat_per_order_cents_applied = models.IntegerField(
        help_text="Snapshot of ``Affiliate.flat_per_order_cents`` at conversion time.",
    )
    commission_cents = models.IntegerField(
        help_text="Computed: floor(gross * bps / 10000) + flat. Frozen at conversion.",
    )

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True,
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    payout = models.ForeignKey(
        "AffiliatePayout",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="conversions",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("affiliate", "order"),
                name="shop_engine_one_conversion_per_order_per_affiliate",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.affiliate.code} → {self.order.order_number} ({self.commission_cents}¢)"


class AffiliatePayout(models.Model):
    """Batched payout — one row per (affiliate, period).

    Created by ``services.affiliates.generate_payout_batch`` which
    sweeps every approved conversion in the period and aggregates the
    commissions. ``mark_payout_paid`` (admin action) flips ``status`` +
    sets ``external_payout_id`` once the operator triggers the real
    transfer (PayPal/bank/etc. — the engine does NOT integrate with
    payout rails directly; that's project-specific).
    """

    STATUS_PENDING = "pending"
    STATUS_PAID = "paid"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_PAID, "Paid"),
        (STATUS_FAILED, "Failed"),
    ]

    affiliate = models.ForeignKey(
        Affiliate, on_delete=models.CASCADE, related_name="payouts",
    )
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    conversion_count = models.PositiveIntegerField(default=0)
    gross_cents = models.IntegerField(default=0)
    commission_cents = models.IntegerField(default=0)
    fee_cents = models.IntegerField(
        default=0,
        help_text="Manual deduction — e.g. PayPal fee passed through to the affiliate.",
    )
    net_cents = models.IntegerField(default=0, help_text="commission_cents - fee_cents")

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True,
    )
    external_payout_id = models.CharField(
        max_length=120,
        blank=True,
        help_text="PayPal payout batch ID, bank reference, etc. Set when marked paid.",
    )
    notes = models.TextField(blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="The operator who triggered the payout.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["affiliate", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"Payout {self.affiliate.code} {self.period_start:%Y-%m-%d} → {self.period_end:%Y-%m-%d} ({self.net_cents}¢)"


# ---------------------------------------------------------------------------
# Provider sync audit log
# ---------------------------------------------------------------------------
class ProviderSyncLog(models.Model):
    """Append-only audit log of every provider interaction.

    Use cases:

    - Debug "why is this product showing the wrong price?" (look up the
      last sync_to_local payload for it).
    - Debug "why didn't this order get dispatched?" (last
      create_order call).
    - Quota tracking (count entries per provider per day).
    """

    STATUS_OK = "ok"
    STATUS_ERROR = "error"

    STATUS_CHOICES = [
        (STATUS_OK, "OK"),
        (STATUS_ERROR, "Error"),
    ]

    provider = models.CharField(max_length=80, db_index=True)
    action = models.CharField(
        max_length=80,
        db_index=True,
        help_text='Free-form: ``sync_to_local``, ``create_order``, ``get_order_status``, ...',
    )
    external_id = models.CharField(max_length=200, blank=True, db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_OK)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["provider", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.provider}/{self.action} → {self.status} @ {self.created_at:%Y-%m-%d %H:%M}"
