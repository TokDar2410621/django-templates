from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PushSubscription",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True,
                    serialize=False, verbose_name="ID",
                )),
                ("endpoint", models.URLField(max_length=500, unique=True)),
                ("p256dh", models.CharField(max_length=255)),
                ("auth", models.CharField(max_length=255)),
                ("user_agent", models.CharField(blank=True, default="", max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_used_at", models.DateTimeField(blank=True, null=True)),
                ("user", models.ForeignKey(
                    on_delete=models.deletion.CASCADE,
                    related_name="push_subscriptions",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "db_table": "notifications_push_subscription",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddIndex(
            model_name="pushsubscription",
            index=models.Index(
                fields=["user", "-created_at"],
                name="notif_push_user_created_idx",
            ),
        ),
        migrations.CreateModel(
            name="NotificationLog",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True,
                    serialize=False, verbose_name="ID",
                )),
                ("channel", models.CharField(
                    choices=[
                        ("email", "Email"),
                        ("push", "Web Push"),
                        ("sms", "SMS"),
                    ],
                    db_index=True,
                    max_length=16,
                )),
                ("status", models.CharField(
                    choices=[
                        ("sent", "Sent"),
                        ("skipped", "Skipped"),
                        ("failed", "Failed"),
                    ],
                    db_index=True,
                    max_length=16,
                )),
                ("subject", models.CharField(blank=True, default="", max_length=255)),
                ("target", models.CharField(
                    blank=True, default="", max_length=320,
                    help_text="Destination — email address, phone E.164, or push endpoint.",
                )),
                ("provider_message_id", models.CharField(blank=True, default="", max_length=255)),
                ("error", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("user", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=models.deletion.CASCADE,
                    related_name="notification_logs",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "db_table": "notifications_log",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddIndex(
            model_name="notificationlog",
            index=models.Index(
                fields=["user", "-created_at"],
                name="notif_log_user_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="notificationlog",
            index=models.Index(
                fields=["channel", "-created_at"],
                name="notif_log_channel_created_idx",
            ),
        ),
    ]
