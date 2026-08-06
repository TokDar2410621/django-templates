"""Legal documents URLs — mount on ``/api/legal/`` in your project."""
from django.urls import path

from .views import LegalDetailView, LegalIndexView


app_name = "legal_cms_pages"

urlpatterns = [
    path("", LegalIndexView.as_view(), name="legal-index"),
    path("<str:kind>/", LegalDetailView.as_view(), name="legal-detail"),
]
