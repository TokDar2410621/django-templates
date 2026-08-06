from django.apps import AppConfig


class AuthJwtOauthConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "auth_jwt_oauth"
    label = "auth_jwt_oauth"
    verbose_name = "SMN Auth (JWT + OAuth)"
