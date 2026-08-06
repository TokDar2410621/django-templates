from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Block",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reason", models.CharField(blank=True, default="", max_length=120)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("blocked", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="rtm_blocks_received", to=settings.AUTH_USER_MODEL)),
                ("blocker", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="rtm_blocks_given", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "realtime_messaging_block", "ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="block",
            constraint=models.UniqueConstraint(fields=("blocker", "blocked"), name="rtm_unique_block_pair"),
        ),
    ]
