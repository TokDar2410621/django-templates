"""shop-engine — single-tenant Django storefront with affiliates + providers.

A full e-commerce subset most personal/SaaS projects actually need: a
product catalogue with variants and reviews, anonymous-or-authenticated
carts, guest-or-user Stripe checkout, an order state machine, a
coupon system with idempotent usage tracking, a hybrid affiliate
program (user-FK *or* email-only with magic-link login), and a small
provider abstraction so the same engine can ship products you stock
yourself OR resell from upstream catalogues (Alibaba, Gelato, ...).

See README.md for integration, SETTINGS.md for the configuration matrix.
"""
default_app_config = "shop_engine.apps.ShopEngineConfig"
