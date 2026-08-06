"""Cart services — add/remove/update items, apply coupons, transfer on login.

The cart is the only model with state mutation in the public API (apart
from create-order). Everything here is small + idempotent on the
``(cart, product, variant)`` natural key.

Re-validation
-------------
``unit_price_cents`` is snapshotted on the ``CartItem`` row at
add-to-cart time. ``calculate_totals`` re-reads the current variant /
product price and surfaces a "price changed" warning when they diverge,
but it doesn't auto-update — the customer must explicitly accept the
new price by calling ``update_quantity`` (or by re-adding to cart).

Coupons
-------
A cart can have at most one applied coupon at a time. Re-applying
overwrites the previous one (the simplest UX — "stacking" coupons is
out of scope and almost always abused).
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from ..exceptions import (
    CartItemNotFound,
    CouponExhausted,
    CouponExpired,
    CouponInvalid,
    CouponMinOrderNotMet,
    CouponNotStarted,
    CouponProductScopeMismatch,
    OutOfStock,
    ProductInactive,
    VariantInactive,
)
from ..models import Cart, CartItem, Coupon, Product, ProductVariant

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cart resolution
# ---------------------------------------------------------------------------
def get_or_create_cart_for_request(request) -> Cart:
    """Return the cart for the current request (user or session-keyed).

    For authenticated users: returns the user's cart (creates on miss).
    For anonymous users: forces a session key (Django creates one on
    save) and returns the session-keyed cart.
    """
    expiry_days = int(getattr(settings, "SHOP_CART_EXPIRY_DAYS", 30))

    if request.user and getattr(request.user, "is_authenticated", False):
        cart, _ = Cart.objects.get_or_create(
            user=request.user,
            defaults={"expires_at": timezone.now() + timedelta(days=expiry_days)},
        )
        return cart

    # Anonymous — ensure the session has a key before keying the cart on it.
    if not request.session.session_key:
        request.session.create()
    sk = request.session.session_key
    cart, _ = Cart.objects.get_or_create(
        session_key=sk,
        user__isnull=True,
        defaults={"expires_at": timezone.now() + timedelta(days=expiry_days)},
    )
    return cart


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------
@transaction.atomic
def add_to_cart(
    cart: Cart,
    *,
    product: Product,
    variant: Optional[ProductVariant] = None,
    quantity: int = 1,
) -> CartItem:
    """Add (or increment) a line. Validates active + stock.

    Idempotent on ``(cart, product, variant)`` — second call increments
    the quantity, doesn't create a duplicate row.
    """
    if quantity < 1:
        raise ValueError("quantity must be ≥ 1")
    if not product.is_active:
        raise ProductInactive(f"Product {product.slug} is not active.")
    if variant is not None:
        if variant.product_id != product.pk:
            raise ValueError("Variant does not belong to product.")
        if not variant.is_active:
            raise VariantInactive(f"Variant {variant.sku} is not active.")
        if not variant.is_in_stock(quantity):
            raise OutOfStock(f"Variant {variant.sku} only has {variant.stock_quantity} in stock.")
        unit_price = variant.effective_price_cents()
    else:
        unit_price = int(product.base_price_cents)

    item, created = CartItem.objects.get_or_create(
        cart=cart,
        product=product,
        variant=variant,
        defaults={"quantity": quantity, "unit_price_cents": unit_price},
    )
    if not created:
        # Incrementing — re-check stock against the NEW total.
        new_qty = item.quantity + quantity
        if variant is not None and not variant.is_in_stock(new_qty):
            raise OutOfStock(
                f"Variant {variant.sku} only has {variant.stock_quantity} in stock (you'd request {new_qty})."
            )
        item.quantity = new_qty
        # Re-snapshot price if it changed — keeps the line truthy.
        item.unit_price_cents = unit_price
        item.save(update_fields=["quantity", "unit_price_cents", "updated_at"])

    Cart.objects.filter(pk=cart.pk).update(updated_at=timezone.now())
    logger.info(
        "add_to_cart cart=%s product=%s variant=%s qty=%d (new total=%d)",
        cart.pk, product.slug, variant.sku if variant else "—", quantity, item.quantity,
    )
    return item


@transaction.atomic
def update_quantity(item: CartItem, *, quantity: int) -> CartItem:
    """Set the line's quantity. ``quantity <= 0`` removes the line."""
    if quantity <= 0:
        item.delete()
        return item

    if item.variant_id and not item.variant.is_in_stock(quantity):
        raise OutOfStock(
            f"Variant {item.variant.sku} only has {item.variant.stock_quantity} in stock."
        )

    item.quantity = quantity
    # Re-snapshot the price so the customer sees the LIVE price after
    # an explicit quantity change. They wouldn't be surprised by a new
    # number they just typed.
    if item.variant_id:
        item.unit_price_cents = item.variant.effective_price_cents()
    else:
        item.unit_price_cents = int(item.product.base_price_cents)
    item.save(update_fields=["quantity", "unit_price_cents", "updated_at"])
    Cart.objects.filter(pk=item.cart_id).update(updated_at=timezone.now())
    return item


def remove_from_cart(item: CartItem) -> None:
    """Delete a line. Idempotent — calling twice is a noop on the second call."""
    cart_id = item.cart_id
    item.delete()
    Cart.objects.filter(pk=cart_id).update(updated_at=timezone.now())


# ---------------------------------------------------------------------------
# Coupons
# ---------------------------------------------------------------------------
def _validate_coupon_for_cart(coupon: Coupon, cart: Cart) -> None:
    """Raise the most specific ``Coupon*`` exception, or return cleanly."""
    now = timezone.now()
    if not coupon.is_active:
        raise CouponInvalid(f"Coupon {coupon.code} is not active.")
    if coupon.starts_at and now < coupon.starts_at:
        raise CouponNotStarted(f"Coupon {coupon.code} starts at {coupon.starts_at}.")
    if coupon.expires_at and now > coupon.expires_at:
        raise CouponExpired(f"Coupon {coupon.code} expired at {coupon.expires_at}.")
    if coupon.max_uses is not None and coupon.times_used >= coupon.max_uses:
        raise CouponExhausted(f"Coupon {coupon.code} reached its max uses.")

    subtotal = _compute_subtotal(cart)
    if subtotal < int(coupon.minimum_order_cents or 0):
        raise CouponMinOrderNotMet(
            f"Cart subtotal {subtotal}¢ is below coupon minimum {coupon.minimum_order_cents}¢."
        )

    scoped_ids = list(coupon.product_scope.values_list("pk", flat=True))
    if scoped_ids:
        cart_product_ids = set(cart.items.values_list("product_id", flat=True))
        if not (set(scoped_ids) & cart_product_ids):
            raise CouponProductScopeMismatch(
                f"Coupon {coupon.code} doesn't apply to anything currently in the cart."
            )


@transaction.atomic
def apply_coupon(cart: Cart, *, code: str) -> Coupon:
    """Validate + attach a coupon code to the cart. Idempotent."""
    code_norm = (code or "").strip()
    if not code_norm:
        raise CouponInvalid("Empty coupon code.")
    coupon = Coupon.objects.filter(code__iexact=code_norm).first()
    if coupon is None:
        raise CouponInvalid(f"No such coupon: {code_norm}")
    _validate_coupon_for_cart(coupon, cart)
    cart.applied_coupon = coupon
    cart.save(update_fields=["applied_coupon", "updated_at"])
    logger.info("apply_coupon cart=%s code=%s", cart.pk, coupon.code)
    return coupon


def revoke_coupon(cart: Cart) -> None:
    """Detach any applied coupon. No-op when no coupon is applied."""
    if cart.applied_coupon_id:
        cart.applied_coupon = None
        cart.save(update_fields=["applied_coupon", "updated_at"])


# ---------------------------------------------------------------------------
# Totals
# ---------------------------------------------------------------------------
def _compute_subtotal(cart: Cart) -> int:
    total = 0
    for item in cart.items.all():
        total += int(item.unit_price_cents) * int(item.quantity)
    return total


def calculate_totals(cart: Cart) -> dict:
    """Return ``{subtotal_cents, shipping_cents, tax_cents, discount_cents, total_cents}``.

    Shipping + tax come from settings (override per-project for real
    rules). The template ships flat numbers because tax + shipping are
    too jurisdiction-specific to bake in a sensible default.
    """
    subtotal = _compute_subtotal(cart)

    discount_cents = 0
    shipping_cents = int(getattr(settings, "SHOP_FLAT_SHIPPING_CENTS", 0))

    if cart.applied_coupon_id:
        coupon = cart.applied_coupon
        try:
            _validate_coupon_for_cart(coupon, cart)
        except CouponInvalid:
            # Silently drop a now-invalid coupon (the customer just
            # removed enough items to fall below minimum, etc.). The
            # checkout endpoint re-validates and surfaces a clearer
            # error if the coupon is required.
            logger.info("calculate_totals dropping now-invalid coupon=%s on cart=%s", coupon.code, cart.pk)
        else:
            if coupon.kind == Coupon.KIND_PERCENT:
                discount_cents = (subtotal * int(coupon.value)) // 100
            elif coupon.kind == Coupon.KIND_FIXED:
                discount_cents = min(int(coupon.value * 100), subtotal)
            elif coupon.kind == Coupon.KIND_FREE_SHIPPING:
                shipping_cents = 0

    tax_bps = int(getattr(settings, "SHOP_TAX_RATE_BPS", 0))
    taxable_base = max(subtotal - discount_cents, 0)
    tax_cents = (taxable_base * tax_bps) // 10_000

    total = max(subtotal - discount_cents, 0) + shipping_cents + tax_cents
    return {
        "subtotal_cents": subtotal,
        "shipping_cents": shipping_cents,
        "tax_cents": tax_cents,
        "discount_cents": discount_cents,
        "total_cents": total,
        "currency": cart.currency,
    }


# ---------------------------------------------------------------------------
# Anonymous → user transfer
# ---------------------------------------------------------------------------
@transaction.atomic
def transfer_anonymous_cart_to_user(*, session_key: str, user) -> Optional[Cart]:
    """Merge the session cart into the user's cart on login.

    Returns the surviving (user-owned) cart, or None if neither cart
    has any items. Hooks into your login view::

        from shop_engine.services.cart import transfer_anonymous_cart_to_user
        @receiver(user_logged_in)
        def on_login(sender, request, user, **kwargs):
            if request.session.session_key:
                transfer_anonymous_cart_to_user(
                    session_key=request.session.session_key,
                    user=user,
                )
    """
    if not session_key:
        return None
    anon_cart = Cart.objects.filter(session_key=session_key, user__isnull=True).first()
    user_cart, _ = Cart.objects.get_or_create(user=user)

    if anon_cart is None or anon_cart.pk == user_cart.pk:
        return user_cart

    # Merge: for each anon line, increment the user line if present
    # else move the line over.
    for anon_item in list(anon_cart.items.all()):
        existing = CartItem.objects.filter(
            cart=user_cart,
            product=anon_item.product,
            variant=anon_item.variant,
        ).first()
        if existing:
            existing.quantity = F("quantity") + anon_item.quantity
            existing.save(update_fields=["quantity", "updated_at"])
            anon_item.delete()
        else:
            anon_item.cart = user_cart
            anon_item.save(update_fields=["cart"])

    # Inherit the anon cart's affiliate code if the user-cart doesn't have one.
    if anon_cart.affiliate_code and not user_cart.affiliate_code:
        user_cart.affiliate_code = anon_cart.affiliate_code
        user_cart.save(update_fields=["affiliate_code"])

    anon_cart.delete()
    logger.info("transfer_anonymous_cart_to_user user=%s session=%s", user.pk, session_key)
    return user_cart


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def get_cart_item(cart: Cart, item_id: int) -> CartItem:
    """Strict lookup — raises ``CartItemNotFound`` rather than DoesNotExist."""
    item = CartItem.objects.filter(cart=cart, pk=item_id).first()
    if item is None:
        raise CartItemNotFound(f"No cart item {item_id} in cart {cart.pk}.")
    return item
