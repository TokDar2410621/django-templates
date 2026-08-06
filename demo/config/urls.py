"""La vitrine expose chaque app sous /api/<slug>/ et un état des lieux en /.

La page racine dit ce qui est monté et ce qui dort (clé absente) : le même
langage que le battement de coeur du cerveau. Une app qui boote ici prouve
que le template s'intègre tel quel.
"""
import os

from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


APPS_MONTEES = [
    ("auth", "auth_jwt_oauth.urls", None),
    ("legal", "legal_cms_pages.urls", None),
    ("ai", "conversational_ai_engine.urls", "ANTHROPIC_API_KEY"),
    ("billing", "saas_billing_credits_quota.urls", "STRIPE_SECRET_KEY"),
    ("notifications", "notifications_multichannel.urls", "RESEND_API_KEY"),
    ("teams", "team_membership_invites.urls", None),
    ("tokens", "hashed_api_tokens.urls", None),
    ("qr", "qr_tag_activation_batches.urls", None),
    ("moderation", "moderation_audit_reports.urls", None),
    ("connect", "stripe_connect_multivendor.urls", "STRIPE_SECRET_KEY"),
    ("newsletter", "newsletter_engine.urls", "RESEND_API_KEY"),
    ("shop", "shop_engine.urls", "STRIPE_SECRET_KEY"),
    ("messaging", "realtime_messaging.urls", "REDIS_URL"),
    ("voice", "voice_messages.urls", None),
]

from django.conf import settings as _s

if _s.POSTGRES:
    APPS_MONTEES.append(("rag", "rag_memory_pgvector.urls", "VOYAGE_API_KEY"))


def accueil(request):
    apps = []
    for slug, module, cle in APPS_MONTEES:
        etat = "actif"
        if cle and not os.environ.get(cle, "").strip():
            etat = f"dormant ({cle} absent)"
        apps.append({"app": module.split(".")[0], "monte_sur": f"/api/{slug}/", "etat": etat})
    if not _s.POSTGRES:
        apps.append({"app": "rag_memory_pgvector", "monte_sur": None,
                     "etat": "non monté (exige Postgres + pgvector)"})
    return JsonResponse(
        {
            "librairie": "django-templates (TokDar2410621, privé)",
            "role": "vitrine : preuve vivante que les 13 templates bootent et coexistent",
            "apps": apps,
            "admin": "/admin/",
        },
        json_dumps_params={"ensure_ascii": False, "indent": 2},
    )


urlpatterns = [
    path("", accueil),
    path("admin/", admin.site.urls),
]
for slug, module, _cle in APPS_MONTEES:
    urlpatterns.append(path(f"api/{slug}/", include(module)))
