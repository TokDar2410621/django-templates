"""Vitrine de la librairie : les 13 apps montées ensemble, déployée sur Railway.

Rôle : prouver en continu que les templates bootent, migrent et coexistent.
Chaque app suit le critère de la lib (settings via getattr + défauts sains),
donc ce settings reste minimal : tout ce qui exige une clé externe (Stripe,
Resend, Twilio, Anthropic, Voyage) reste dormant tant que la variable d'env
n'existe pas, exactement comme les sondes du cerveau.
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # demo/
REPO_DIR = BASE_DIR.parent  # racine du repo

# Les apps de la lib se nomment sans préfixe (name = "auth_jwt_oauth") : la
# racine apps/ doit être sur le path, comme dans les projets consommateurs.
sys.path.insert(0, str(REPO_DIR / "apps"))

SECRET_KEY = os.environ.get("SECRET_KEY", "demo-insecure-key-dev-only")
DEBUG = os.environ.get("DEBUG", "off").lower() in ("1", "on", "true")

_hote_railway = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
# healthcheck.railway.app : l'hote avec lequel Railway sonde le service au
# deploiement ; sans lui, l'app est saine mais le deploy echoue au healthcheck.
ALLOWED_HOSTS = [h for h in ["localhost", "127.0.0.1", "healthcheck.railway.app", _hote_railway] if h]
CSRF_TRUSTED_ORIGINS = [f"https://{_hote_railway}"] if _hote_railway else []

# --- base de données -------------------------------------------------------
# Railway fournit DATABASE_URL (Postgres + pgvector). En local sans Postgres,
# sqlite suffit pour tout SAUF rag_memory_pgvector (types vector).
import dj_database_url

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}", conn_max_age=600
    )
}
POSTGRES = DATABASES["default"]["ENGINE"].endswith("postgresql")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    # DRF + auth
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "allauth.socialaccount.providers.apple",
    "dj_rest_auth",
    # La librairie, au complet
    "auth_jwt_oauth",
    "legal_cms_pages",
    "conversational_ai_engine",
    "saas_billing_credits_quota",
    "notifications_multichannel",
    "team_membership_invites",
    "hashed_api_tokens",
    "qr_tag_activation_batches",
    "moderation_audit_reports",
    "stripe_connect_multivendor",
    "newsletter_engine",
    "shop_engine",
]
if POSTGRES:
    # pgvector exige Postgres : l'app rag ne se monte que là où elle peut vivre.
    INSTALLED_APPS.append("rag_memory_pgvector")

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
SITE_ID = 1

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
}

# La lib est 100 % JWT : pas de tokens DRF classiques (dj-rest-auth l'exige
# explicitement, sinon il reclame rest_framework.authtoken).
REST_AUTH = {"USE_JWT": True, "TOKEN_MODEL": None, "SESSION_LOGIN": False}

LANGUAGE_CODE = "fr-ca"
TIME_ZONE = "America/Montreal"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
