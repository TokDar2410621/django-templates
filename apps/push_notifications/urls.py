from django.urls import path

from .views import DeviceView, TestPushView, VapidPublicKeyView

app_name = "push_notifications"

urlpatterns = [
    path("cle-vapid/", VapidPublicKeyView.as_view(), name="cle-vapid"),
    path("appareils/", DeviceView.as_view(), name="appareils"),
    path("test/", TestPushView.as_view(), name="test"),
]
