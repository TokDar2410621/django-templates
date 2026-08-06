# SETTINGS — hashed-api-tokens

## pip dependencies

```
djangorestframework>=3.14
```

Optional:

```
django-unfold        # if your admin uses Unfold; otherwise falls back to stock ModelAdmin
```

## INSTALLED_APPS

```python
INSTALLED_APPS = [
    # ...
    "rest_framework",
    "hashed_api_tokens",
]
```

## URLs

```python
# config/urls.py
from django.urls import path, include

urlpatterns = [
    # ...
    path("api/tokens/", include("hashed_api_tokens.urls")),
]
```

## Configurable settings (all optional)

```python
# settings.py — single knob. Change the prefix to your product code so
# tokens are recognizable in logs and config files.
API_TOKEN_PREFIX = "tkn"   # default — produces tokens like "tkn_aB7cD…"
# API_TOKEN_PREFIX = "smn"   # SendMeNow
# API_TOKEN_PREFIX = "fin"   # FindItNow
# API_TOKEN_PREFIX = "btb"   # blog-dashboard
```

NOTE: changing `API_TOKEN_PREFIX` does NOT migrate existing tokens.
Already-issued tokens keep the prefix they were minted with — the new
prefix only applies to tokens created AFTER the setting change. Existing
tokens continue to authenticate correctly because authentication looks
up by hash, not by prefix.

## DRF integration — adding the auth backend

For per-view use (recommended for narrow attack surface):

```python
from hashed_api_tokens.authentication import HashedTokenAuthentication

class MyView(APIView):
    authentication_classes = [HashedTokenAuthentication]
    permission_classes = [IsAuthenticated]
```

For project-wide use (stacked alongside JWT/session for the dashboard):

```python
# settings.py
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "hashed_api_tokens.authentication.HashedTokenAuthentication",
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
}
```

The backend returns `None` when no token header is present, so it stacks
cleanly with others — it never blocks dashboard requests.

## Env vars

None required.

## Post-install verification

```bash
python manage.py check
python manage.py migrate hashed_api_tokens
python manage.py test hashed_api_tokens
# or with pytest:
pytest apps/hashed_api_tokens/tests/

# curl smoke (you need a session/JWT for these — they manage tokens, they
# are not protected by tokens themselves):

# 1. Create a token (returns the plain value ONCE)
curl -s -X POST http://127.0.0.1:8000/api/tokens/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <YOUR_JWT>" \
  -d '{"name": "n8n production"}'

# 2. Use that plain token to call a token-protected endpoint
curl -s http://127.0.0.1:8000/api/v1/whatever/ \
  -H "Authorization: Bearer tkn_…"

# 3. Or via the X-Api-Key alias
curl -s http://127.0.0.1:8000/api/v1/whatever/ \
  -H "X-Api-Key: tkn_…"

# 4. List your tokens (plain is NOT in the response)
curl -s http://127.0.0.1:8000/api/tokens/ \
  -H "Authorization: Bearer <YOUR_JWT>"

# 5. Revoke a token
curl -s -X POST http://127.0.0.1:8000/api/tokens/7/revoke/ \
  -H "Authorization: Bearer <YOUR_JWT>"
```
