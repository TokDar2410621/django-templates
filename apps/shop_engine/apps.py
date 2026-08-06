from django.apps import AppConfig


class ShopEngineConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "shop_engine"
    label = "shop_engine"
    verbose_name = "Shop Engine"

    def ready(self) -> None:  # pragma: no cover - signal wiring
        # Importing the signals module registers receivers as a side
        # effect. We swallow ImportError so a project that strips out
        # the signals module still boots (everything still works, the
        # is_verified_purchase flag just won't auto-flip on reviews).
        try:
            from . import signals  # noqa: F401
        except ImportError:
            pass
