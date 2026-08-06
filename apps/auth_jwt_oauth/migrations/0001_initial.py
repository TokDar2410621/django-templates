from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="UserProfile",
            fields=[
                (
                    "user",
                    models.OneToOneField(
                        on_delete=models.deletion.CASCADE,
                        primary_key=True,
                        related_name="smn_auth_profile",
                        serialize=False,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "display_name",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text=(
                            "Nom d'affichage (montré dans l'app, défini à l'inscription)."
                        ),
                        max_length=80,
                    ),
                ),
                (
                    "phone_e164",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text=(
                            "Numéro de téléphone au format international (commence par +)."
                        ),
                        max_length=20,
                    ),
                ),
                ("phone_verified", models.BooleanField(default=False)),
                (
                    "is_banned",
                    models.BooleanField(
                        db_index=True,
                        default=False,
                        help_text=(
                            "Utilisateur banni — la connexion par mot de passe est refusée."
                        ),
                    ),
                ),
                (
                    "terms_accepted_at",
                    models.DateTimeField(
                        blank=True,
                        help_text=(
                            "Horodatage de l'acceptation des CGU / politique de "
                            "confidentialité. Null pour les comptes pré-existants."
                        ),
                        null=True,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "smn_auth_user_profile",
                "verbose_name": "User profile",
                "verbose_name_plural": "User profiles",
            },
        ),
    ]
