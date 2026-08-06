from django.apps import AppConfig


class HashedApiTokensConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "hashed_api_tokens"
    label = "hashed_api_tokens"
    verbose_name = "Hashed API Tokens"
