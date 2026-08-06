from django.apps import AppConfig


class TeamMembershipInvitesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "team_membership_invites"
    label = "team_membership_invites"
    verbose_name = "Team membership & invites"

    def ready(self) -> None:  # pragma: no cover - signal import side effect
        # Import signals so they are registered when Django starts.
        from . import signals  # noqa: F401
