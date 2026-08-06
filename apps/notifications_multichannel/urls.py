"""URLs — mount on ``/api/notifications/`` in your project.

```python
# config/urls.py
urlpatterns = [
    # ...
    path("api/notifications/", include("notifications_multichannel.urls")),
]
```
"""
from django.urls import path

from .views import PushSubscribeView, PushUnsubscribeView, TestNotificationView

app_name = "notifications_multichannel"

urlpatterns = [
    path("push/subscribe/", PushSubscribeView.as_view(), name="push-subscribe"),
    path("push/unsubscribe/", PushUnsubscribeView.as_view(), name="push-unsubscribe"),
    path("test/", TestNotificationView.as_view(), name="test-notification"),
]
