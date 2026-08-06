"""Newsletter engine URLs.

Mount on ``/api/newsletter/`` (admin/internal + public) AND on
``/newsletter/`` (tracking + webhooks). Splitting the prefixes is optional;
it just makes nginx routing easier.

Suggested wiring::

    # config/urls.py
    urlpatterns = [
        ...
        path("api/newsletter/", include("newsletter_engine.urls")),
        # Tracking + webhooks already included under the same prefix below;
        # if you want them on a separate hostname, set
        # NEWSLETTER_TRACKING_BASE_URL to that hostname.
    ]
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AutomationViewSet,
    CampaignViewSet,
    ConfirmView,
    MailingListViewSet,
    PreferencesView,
    ResendWebhookView,
    SegmentViewSet,
    SubscribeView,
    SubscriberViewSet,
    TagViewSet,
    TrackClickView,
    TrackOpenView,
    UnsubscribeView,
)


app_name = "newsletter_engine"

# Admin/internal CRUD router. Mounted at the include() root, so paths look
# like /api/newsletter/subscribers/, /api/newsletter/campaigns/, etc.
router = DefaultRouter()
router.register(r"subscribers", SubscriberViewSet, basename="subscriber")
router.register(r"lists", MailingListViewSet, basename="list")
router.register(r"tags", TagViewSet, basename="tag")
router.register(r"segments", SegmentViewSet, basename="segment")
router.register(r"campaigns", CampaignViewSet, basename="campaign")
router.register(r"automations", AutomationViewSet, basename="automation")


urlpatterns = [
    # Public — no auth.
    path("subscribe/", SubscribeView.as_view(), name="subscribe"),
    path("confirm/", ConfirmView.as_view(), name="confirm"),
    path("unsubscribe/", UnsubscribeView.as_view(), name="unsubscribe"),
    path("preferences/", PreferencesView.as_view(), name="preferences"),

    # Tracking — no auth.
    path(
        "track/open/<str:delivery_token>.gif",
        TrackOpenView.as_view(), name="track-open",
    ),
    path(
        "track/click/<str:delivery_token>/",
        TrackClickView.as_view(), name="track-click",
    ),

    # Webhooks — no auth, HMAC-verified.
    path("webhooks/resend/", ResendWebhookView.as_view(), name="webhook-resend"),

    # Admin/internal — IsAuthenticated.
    path("", include(router.urls)),
]
