"""URL patterns — mount on ``/api/ai/`` in your project::

    # config/urls.py
    urlpatterns = [
        # ...
        path("api/ai/", include("conversational_ai_engine.urls")),
    ]
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    GenerateView,
    GenerationListView,
    PersonaView,
    StreamingGenerateView,
    TemplateViewSet,
)

app_name = "conversational_ai_engine"

router = DefaultRouter()
router.register(r"templates", TemplateViewSet, basename="ai-template")

urlpatterns = [
    path("generate/", GenerateView.as_view(), name="ai-generate"),
    path("generate/stream/", StreamingGenerateView.as_view(), name="ai-generate-stream"),
    path("persona/", PersonaView.as_view(), name="ai-persona"),
    path("generations/", GenerationListView.as_view(), name="ai-generations"),
    path("", include(router.urls)),
]
