# conversational-ai-engine

═════════════════════════════════════════════
Template : conversational-ai-engine
Version  : 1.0.0
Mode     : EXTRACT-B (REWRITE)
Source   : smart-post-assistant/backend/api (inspiration only)
Stack    : Django 5+ / DRF / anthropic SDK / (unfold optional)
Deps     : `anthropic>=0.34`, `djangorestframework>=3.14`
Used by  : (none yet)
═════════════════════════════════════════════

Pluggable LLM generation pipeline — persona injection, prompt templates,
streaming SSE, vision uploads, audit/billing hook, optional RAG.

## Why this template

* **Provider-agnostic.** A clean `AIProvider` abstraction lets you swap
  Claude → GPT → Gemini without touching call sites. Anthropic is wired
  by default; OpenAI/Gemini stubs are easy to add.
* **Persona injection that survives upgrades.** `PersonaContext` is a
  1-to-1 sidecar that produces a multi-line context block the engine
  prepends to every system prompt — without polluting the User model.
* **User-customisable prompt templates.** Prefix/suffix wrappers + a
  forced tone, owned per user, with at-most-one-default enforced at the
  DB level via a partial unique constraint.
* **Audit + billing in one signal.** Every generation persists with
  token counts and USD cost; `on_generation_complete` fires after save
  so a billing/credits app can wire up via signal — no import coupling.
* **Anonymous trials baked in.** When no user is authenticated, the
  engine falls back to the Django session key. Rate limiting stays in
  the project (the engine just records the key on every row).
* **RAG synergy ready.** Set `AI_RAG_RETRIEVAL_BACKEND` to a callable
  `(user, query) -> [{id, text}]` and retrieved chunks get prepended as
  `CONTEXT:\n...` — pairs naturally with `rag-site-memory-pgvector`.
* **Prompt caching enabled by default.** Anthropic provider marks the
  system prompt with `cache_control={"type": "ephemeral"}` so a long
  persona gets cache-hit pricing on follow-up calls.
* **Streaming via SSE.** `POST /generate/stream/` returns a Server-Sent
  Events response — drop-in for typewriter-style UIs.

## Why EXTRACT-B (rewrite, not copy)

The smart-post-assistant code was tightly coupled to LinkedIn (hook
patterns, hashtag extractors, carousel generators, post-engagement
tracking). Lifting it verbatim into a template would carry social-media
jargon into projects that just need a clean prompt pipeline.

What we **kept and generalised**:
* The `build_prompt_context()` injection pattern (proven in production).
* The 5-tone enum (now overridable via `AI_TONES`).
* The custom `PromptTemplate` prefix/suffix mechanism.
* The anonymous `session_key` model field.
* The base64 image upload pipeline for vision.

What we **dropped**:
* LinkedIn-specific carousel + infographic generators.
* "Post LinkedIn" terminology — now "generated content".
* Tone-specific system prompts loaded with LinkedIn jargon.
* `LinkedInAccount`, `ScheduledPost`, `PublishedPost.engagement_rate`
  (those are LinkedIn integration concerns, not generation concerns).

## API

| Method | Path                       | Auth     | Purpose                              |
|--------|----------------------------|----------|--------------------------------------|
| POST   | `/api/ai/generate/`        | optional | One-shot generation (JSON or multipart) |
| POST   | `/api/ai/generate/stream/` | optional | SSE streaming generation             |
| GET    | `/api/ai/persona/`         | required | Read the caller's persona            |
| PUT    | `/api/ai/persona/`         | required | Partial update                       |
| GET    | `/api/ai/templates/`       | required | List user + built-in templates       |
| POST   | `/api/ai/templates/`       | required | Create a template                    |
| PUT    | `/api/ai/templates/{id}/`  | required | Update (own templates only)          |
| DELETE | `/api/ai/templates/{id}/`  | required | Delete (own templates only)          |
| GET    | `/api/ai/generations/?limit=N` | optional | Recent generations (own or by session) |

## Quickstart

```bash
pip install anthropic djangorestframework
```

Add to `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    # ...
    "rest_framework",
    "conversational_ai_engine",
]
```

Wire URLs:

```python
# config/urls.py
urlpatterns = [
    # ...
    path("api/ai/", include("conversational_ai_engine.urls")),
]
```

Migrate:

```bash
python manage.py migrate
```

Smoke test:

```bash
curl -s -X POST http://127.0.0.1:8000/api/ai/generate/ \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Write a haiku about Django.", "tone": "inspirant"}'
```

## Model choice

Default model is `claude-sonnet-4-6` — the sweet spot of cost and quality
for most apps. Switch in one line:

```python
# settings.py
AI_DEFAULT_MODEL = "claude-opus-4-7"  # higher quality, ~5x the cost
# or per-call:
generate(prompt="...", model="claude-haiku-4-6")
```

| Model               | When to use                                  |
|---------------------|----------------------------------------------|
| `claude-haiku-4-6`  | Routing, classification, short responses     |
| `claude-sonnet-4-6` | **Default.** Most generation, persona apps   |
| `claude-opus-4-7`   | Long-form, complex reasoning, brand-critical |

## RAG synergy

To enable retrieval-augmented generation, set a backend callable:

```python
# settings.py
AI_RAG_RETRIEVAL_BACKEND = "rag_site_memory_pgvector.api.search_for_user"

# Backend signature:
#   def search_for_user(*, user, query) -> list[dict]
#       return [
#           {"id": "chunk-uuid-1", "text": "Document excerpt..."},
#           ...
#       ]
```

Retrieved chunks are prepended to the user input as `CONTEXT:\n...`. The
chunk IDs are stored on `Generation.retrieved_memory_ids` so you can
audit what was used.

If the backend raises, the engine logs and falls back to no-RAG — your
generation endpoint never goes down because the vector DB is flaky.

## Billing / quota wiring

Connect a receiver to `on_generation_complete` (typically in your billing
app's `apps.py::ready`):

```python
from conversational_ai_engine.signals import on_generation_complete

def deduct_credits(sender, *, user, generation, **kwargs):
    if user is None:
        return  # anonymous — handle via rate limit
    cost_cents = int(generation.cost_usd * 100)
    YourBilling.objects.deduct(
        user=user, amount_cents=cost_cents, reason="ai_generation",
    )

on_generation_complete.connect(deduct_credits, dispatch_uid="billing")
```

The signal fires AFTER the `Generation` row is persisted, in the same
transaction. Receivers always see a saved instance.

## Testing

```bash
pytest apps/conversational_ai_engine/tests/
```

The test suite uses a `FakeAIProvider` that echoes input back with
deterministic token counts — no API key, no network, no flakes.

## What this does NOT include

* **The billing / credits backend.** That's `saas-billing-credits-quota`.
  This template only emits the signal.
* **The RAG storage.** That's `rag-site-memory-pgvector`. This template
  only consumes a retrieval callable.
* **Rate limiting.** Use DRF throttling or a middleware in your project.
  The engine records the session key — limiting it is your call.
* **Conversation memory (multi-turn).** Each call is one-shot; if you
  need multi-turn, build a chat session model on top and pass historic
  messages via the `messages` kwarg on the provider (the abstraction
  supports it, the engine's `generate()` helper just doesn't use it
  yet).

See [SETTINGS.md](./SETTINGS.md) for the full configuration matrix.
