"""URL config — mount on ``/api/tokens/`` (or wherever you like).

Example in ``config/urls.py``::

    path("api/tokens/", include("hashed_api_tokens.urls")),
"""
from django.urls import path

from .views import TokenListCreateView, TokenRevokeView


app_name = "hashed_api_tokens"

urlpatterns = [
    path("", TokenListCreateView.as_view(), name="token-list-create"),
    path("<int:pk>/revoke/", TokenRevokeView.as_view(), name="token-revoke"),
]
