"""Services layer — business logic, broken into one module per area.

Each submodule owns one workflow:

- ``catalog``      — provider sync + upsert.
- ``cart``         — add/remove/update items + coupon apply + anon→user transfer.
- ``checkout``     — turn a Cart into an Order + a Stripe PaymentIntent.
- ``orders``       — state machine transitions + refunds.
- ``fulfillment``  — dispatch to provider, mark shipped / delivered.
- ``affiliates``   — create, magic-link, click tracking, conversion attribution, payouts.
- ``reviews``      — submit review + verified-purchase detection.

Convention: each service function is the entry point a view (or task,
or admin action) calls. They do their own transactions, raise
``shop_engine.exceptions`` on failure, and log via
``logger = logging.getLogger(__name__)``.

Anything that doesn't write — counts, lookups, dashboards — lives in
``selectors.py`` at the top of the package, not in services.
"""
from __future__ import annotations
