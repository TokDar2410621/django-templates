"""URL patterns for qr_tag_activation_batches.

The template exposes TWO mount points because the public scan URL needs
to live at the site root (``/q/<slug>/``) while the API lives under
``/api/activation/``. Wire them like this in your project::

    # config/urls.py
    from django.urls import include, path
    from qr_tag_activation_batches.urls import api_urlpatterns, scan_urlpatterns

    urlpatterns = [
        # ...
        path("",                  include(scan_urlpatterns)),   # /q/<slug>/
        path("api/activation/",   include(api_urlpatterns)),    # API
    ]

If you want one mount point only, ``urlpatterns`` (the merged list) is
also exported for convenience — but you'll get the API namespaced under
``api/`` and the scan endpoint at ``q/<slug>/`` relative to the mount.
"""
from __future__ import annotations

from django.urls import path

from .views import (
    BatchDetailView,
    BatchListView,
    ClaimView,
    PhotoClaimView,
    ScanView,
)


app_name = "qr_tag_activation_batches"


# Public scan endpoint — mount at site root.
scan_urlpatterns = [
    path("q/<str:slug>/", ScanView.as_view(), name="scan"),
]


# All API endpoints — mount under ``api/activation/``.
api_urlpatterns = [
    path("claim/",        ClaimView.as_view(),       name="claim"),
    path("photo-claim/",  PhotoClaimView.as_view(),  name="photo-claim"),
    path("batches/",      BatchListView.as_view(),   name="batch-list"),
    path("batches/<int:pk>/", BatchDetailView.as_view(), name="batch-detail"),
]


# Convenience export — for callers who do a single ``include()``. Prefer
# wiring ``scan_urlpatterns`` and ``api_urlpatterns`` separately (see the
# docstring at the top of this module) so the scan endpoint lives at the
# site root.
urlpatterns = scan_urlpatterns + api_urlpatterns
