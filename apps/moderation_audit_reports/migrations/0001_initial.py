from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Report",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("target_type", models.CharField(db_index=True, max_length=32)),
                ("target_id", models.CharField(db_index=True, max_length=100)),
                ("reason", models.CharField(
                    choices=[
                        ("spam", "Spam"),
                        ("harassment", "Harassment"),
                        ("threat", "Threat / violence"),
                        ("illegal", "Illegal content"),
                        ("hate", "Hate speech"),
                        ("nsfw", "NSFW / explicit"),
                        ("self_harm", "Self-harm"),
                        ("minor", "Involves a minor"),
                        ("other", "Other"),
                    ],
                    db_index=True,
                    default="other",
                    max_length=32,
                )),
                ("description", models.TextField(blank=True)),
                ("evidence_url", models.URLField(blank=True)),
                ("priority", models.PositiveSmallIntegerField(
                    choices=[(0, "Low"), (1, "Medium"), (2, "High"), (3, "Urgent")],
                    db_index=True,
                    default=1,
                )),
                ("status", models.CharField(
                    choices=[
                        ("open", "Open"),
                        ("triaged", "Triaged"),
                        ("actioned", "Actioned"),
                        ("dismissed", "Dismissed"),
                    ],
                    db_index=True,
                    default="open",
                    max_length=16,
                )),
                ("actioned_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("actioned_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=models.deletion.SET_NULL,
                    related_name="reports_actioned",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("reporter", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=models.deletion.SET_NULL,
                    related_name="reports_filed",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("target_owner", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=models.deletion.SET_NULL,
                    related_name="reports_received",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "db_table": "moderation_report",
                "ordering": ("-priority", "-created_at"),
            },
        ),
        migrations.CreateModel(
            name="BannedUser",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reason", models.TextField(blank=True)),
                ("banned_until", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("banned_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=models.deletion.SET_NULL,
                    related_name="bans_issued",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("user", models.OneToOneField(
                    on_delete=models.deletion.CASCADE,
                    related_name="ban_record",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "db_table": "moderation_banned_user",
                "ordering": ("-created_at",),
            },
        ),
        migrations.CreateModel(
            name="ModerationLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(db_index=True, max_length=64)),
                ("target_type", models.CharField(db_index=True, max_length=32)),
                ("target_id", models.CharField(db_index=True, max_length=100)),
                ("before", models.JSONField(blank=True, null=True)),
                ("after", models.JSONField(blank=True, null=True)),
                ("note", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("actor", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=models.deletion.SET_NULL,
                    related_name="moderation_actions",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "db_table": "moderation_log",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddIndex(
            model_name="report",
            index=models.Index(
                fields=["target_type", "target_id"],
                name="mod_report_target_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="report",
            index=models.Index(
                fields=["status", "-priority"],
                name="mod_report_status_prio_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="moderationlog",
            index=models.Index(
                fields=["target_type", "target_id"],
                name="mod_log_target_idx",
            ),
        ),
    ]
