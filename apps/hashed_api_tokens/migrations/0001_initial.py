import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ApiToken",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "name",
                    models.CharField(
                        help_text=(
                            "Friendly label set by the user. One token per integration is "
                            "recommended. E.g. 'n8n production', 'Zapier', 'CI runner'."
                        ),
                        max_length=100,
                    ),
                ),
                (
                    "key_hash",
                    models.CharField(
                        db_index=True,
                        help_text="SHA256 of the plain token. Never reversible.",
                        max_length=64,
                        unique=True,
                    ),
                ),
                (
                    "key_prefix",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="First chars of the plain token — for UI identification only.",
                        max_length=12,
                    ),
                ),
                (
                    "last_used_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="Updated on each successful auth (rate-limited to avoid hammering the DB).",
                        null=True,
                    ),
                ),
                (
                    "revoked_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="Set when the user (or admin) revokes the token. NULL = active.",
                        null=True,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        help_text="Owner of this token. Cascade-deleted with the user.",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="api_tokens",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "hashed_api_token",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="apitoken",
            index=models.Index(
                fields=["user", "revoked_at"],
                name="hashed_api_user_rev_idx",
            ),
        ),
    ]
