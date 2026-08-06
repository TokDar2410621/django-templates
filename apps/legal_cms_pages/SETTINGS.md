# SETTINGS — legal-cms-pages

## pip dependencies

```
markdown>=3.5
bleach>=6.0
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
    "legal_cms_pages",
]
```

## URLs

```python
# config/urls.py
from django.urls import path, include

urlpatterns = [
    # ...
    path("api/legal/", include("legal_cms_pages.urls")),
]
```

## Configurable settings (all optional)

```python
# settings.py — all three have sensible defaults; override as needed

# Document kinds — list of (value, label) tuples. Add custom kinds without
# a migration; the field is CharField(max_length=48).
LEGAL_DOCUMENT_KINDS = [
    ("privacy_policy",   "Politique de confidentialité"),
    ("terms_of_service", "Conditions d'utilisation"),
    ("cookies_policy",   "Politique des cookies"),
    ("parental_consent", "Consentement parental"),     # example custom kind
    ("dpa",              "Data Processing Agreement"),  # example custom kind
]

# Languages — list of (code, label) tuples. Codes are 2 chars by default
# (max_length=8 if you need longer codes like "fr-CA").
LEGAL_DOCUMENT_LANGUAGES = [
    ("fr", "Français"),
    ("en", "English"),
    ("es", "Español"),
]

# Fallback language when a requested language has no published version.
LEGAL_DEFAULT_LANGUAGE = "fr"
```

## Env vars

None required.

## Post-install verification

```bash
python manage.py check
python manage.py migrate
python manage.py test legal_cms_pages
# or with pytest:
pytest apps/legal_cms_pages/tests/

# curl smoke:
curl -s http://127.0.0.1:8000/api/legal/?lang=fr
curl -s http://127.0.0.1:8000/api/legal/privacy_policy/?lang=fr
```
