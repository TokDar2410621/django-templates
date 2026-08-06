# SETTINGS — conversational-ai-engine

## pip dependencies

```
anthropic>=0.34
djangorestframework>=3.14
```

Optional:

```
django-unfold        # if your admin uses Unfold; otherwise stock ModelAdmin
```

## INSTALLED_APPS

```python
INSTALLED_APPS = [
    # ...
    "rest_framework",
    "conversational_ai_engine",
]
```

## URLs

```python
# config/urls.py
from django.urls import path, include

urlpatterns = [
    # ...
    path("api/ai/", include("conversational_ai_engine.urls")),
]
```

## Env vars

| Var                 | Required | Purpose                                |
|---------------------|----------|----------------------------------------|
| `ANTHROPIC_API_KEY` | yes\*    | Anthropic SDK auth. \*Required only when using `AI_DEFAULT_PROVIDER="anthropic"` (the default). Without it the app still boots; generation endpoints return HTTP 401. |

Add to `settings.py`:

```python
import os

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
```

## Configurable settings (all optional)

```python
# settings.py — every entry below has a sensible default

# --- Provider routing -----------------------------------------------------
AI_DEFAULT_PROVIDER = "anthropic"   # default
# Extend the registry with dotted paths for additional providers:
AI_PROVIDERS = {
    # "openai":  "myproject.ai_providers.OpenAIProvider",
    # "gemini":  "myproject.ai_providers.GeminiProvider",
}

# --- Model ---------------------------------------------------------------
AI_DEFAULT_MODEL = "claude-sonnet-4-6"  # default; cheap/quality sweet spot
# Upgrade path for high-quality use cases:
# AI_DEFAULT_MODEL = "claude-opus-4-7"

# --- Tones (overridable without a migration; field is CharField max_length=32) ---
AI_TONES = [
    ("professionnel", "Professionnel"),
    ("inspirant",     "Inspirant"),
    ("storytelling",  "Storytelling"),
    ("educatif",      "Éducatif"),
    ("humoristique",  "Humoristique"),
    # Add custom tones:
    # ("technique",   "Technique"),
]

# --- Prompt caching (Anthropic provider) ---------------------------------
AI_PROMPT_CACHING = True   # default ON; saves money on long personas

# --- Pricing override ----------------------------------------------------
# USD per million tokens; only used for the cost_usd estimate.
AI_MODEL_RATES_PER_MILLION = {
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-7":   (15.0, 75.0),
    "claude-haiku-4-6":  (0.80, 4.0),
}

# --- Anonymous-trial rate limit ------------------------------------------
# Plug into DRF throttling or your own middleware. The engine itself does
# not enforce a limit; it records the session key on every row so your
# limiter can read it.
AI_TRIAL_RATE_LIMIT = "10/day"   # informational; project enforces

# --- RAG retrieval backend (optional) ------------------------------------
# Callable or dotted path. Signature:
#   def backend(*, user, query) -> list[dict]
#       # return [{"id": str, "text": str}, ...]
# Disabled by default.
AI_RAG_RETRIEVAL_BACKEND = None
# Example wiring to the rag-site-memory-pgvector template:
# AI_RAG_RETRIEVAL_BACKEND = "rag_site_memory_pgvector.api.search_for_user"
```

## Wiring billing via signals

```python
# myapp/apps.py
from django.apps import AppConfig


class MyAppConfig(AppConfig):
    name = "myapp"

    def ready(self):
        from conversational_ai_engine.signals import on_generation_complete

        def deduct(sender, *, user, generation, **kwargs):
            if user is None:
                return
            cost_cents = int(generation.cost_usd * 100)
            # ... call your billing app here ...

        on_generation_complete.connect(deduct, dispatch_uid="myapp-deduct")
```

## Post-install verification

```bash
python manage.py check
python manage.py migrate
python manage.py test conversational_ai_engine
# or with pytest:
pytest apps/conversational_ai_engine/tests/

# Smoke (server running on :8000, ANTHROPIC_API_KEY set):
curl -s -X POST http://127.0.0.1:8000/api/ai/generate/ \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Say hi.", "tone": "inspirant"}'

# Stream:
curl -N -X POST http://127.0.0.1:8000/api/ai/generate/stream/ \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Tell me a 3-sentence story."}'
```
