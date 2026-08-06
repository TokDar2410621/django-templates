from django.apps import AppConfig


class RealtimeMessagingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "realtime_messaging"
    verbose_name = "Realtime Messaging (Redis + Channels)"
