# Catalog

Detailed technical index of every template. For human-readable summary see
`README.md`. For per-template integration guides see each `apps/<slug>/README.md`.

| Slug | Version | Mode | Source | Depends on | Status |
|---|---|---|---|---|---|
| `legal-cms-pages` | 1.0.0 | EXTRACT-A | FIN/legal | drf, markdown, bleach, unfold | ready |
| `auth-jwt-oauth` | 1.0.0 | EXTRACT-A | FIN/users | drf, simplejwt, allauth, dj-rest-auth | ready |
| `rag-memory-pgvector` | 1.0.0 | EXTRACT-A | Blog/sites_mgmt | pgvector, voyageai | ready |
| `conversational-ai-engine` | 1.0.0 | EXTRACT-B | smart-post | anthropic, drf | ready |
| `saas-billing-credits-quota` | 1.0.0 | EXTRACT-A | Blog/sites_mgmt | stripe, drf | ready |
| `notifications-multichannel` | 1.0.0 | EXTRACT-A | FIN/notifications | resend, pywebpush, twilio | ready |
| `team-membership-invites` | 1.0.0 | EXTRACT-A | FIN/families | drf | ready |
| `hashed-api-tokens` | 1.0.0 | EXTRACT-A | Blog/ApiToken | drf | ready |
| `qr-tag-activation-batches` | 1.0.0 | EXTRACT-A | FIN/activation | drf, unfold | ready |
| `moderation-audit-reports` | 1.0.0 | EXTRACT-A | SMN/moderation | drf, unfold | ready |
| `stripe-connect-multivendor` | 1.0.0 | EXTRACT-B | SMN/shop | stripe, drf, unfold | ready |
| `newsletter-engine` | 1.0.0 | CREATE | (inspired by Blog/Lead funnel) | drf, requests, celery (opt) | ready |
| `shop-engine` | 1.0.0 | CREATE | (inspired by SMN/shop) | drf, stripe, celery (opt) | ready |

## Snippets (`snippets/`)

Single-file utilities — copy-paste into settings/middleware/utils, not full Django apps.

| File | Purpose | Source |
|---|---|---|
| `storage_s3_autoswitch.py` | Auto-flip STORAGES between FileSystem and S3 | SMN + FIN |
| `stripe_mode_toggle.py` | Resolve Stripe keys per `STRIPE_MODE=test\|live` | SMN + FIN |
| `redis_dual_db.py` | 2-DB Redis (ephemeral vs cache/broker) | SMN + FIN |
| `channels_jwt_middleware.py` | WebSocket JWT auth via `?token=` query param | FIN |
| `pem_env_loader.py` | Load PEM keys from path or inline `\n`-escaped env | FIN |
| `drf_ratelimit_429.py` | DRF EXCEPTION_HANDLER: Ratelimited → 429 | FIN |
