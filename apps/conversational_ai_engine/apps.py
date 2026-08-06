from django.apps import AppConfig


class ConversationalAiEngineConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "conversational_ai_engine"
    label = "conversational_ai_engine"
    verbose_name = "Conversational AI Engine"

    def ready(self) -> None:
        # Import the signal module so receivers attached to
        # ``on_generation_complete`` at import-time are registered. We do not
        # connect any default receivers here — projects opt in.
        from . import signals  # noqa: F401
