import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

import voice_messages.models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="VoiceMessage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("uuid", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("file", models.FileField(upload_to=voice_messages.models.chemin_upload)),
                ("mime_type", models.CharField(max_length=60)),
                ("size_bytes", models.PositiveIntegerField()),
                ("duration_seconds", models.PositiveIntegerField()),
                ("ref", models.CharField(blank=True, db_index=True, default="", max_length=120)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("sender", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="voice_messages", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "voice_messages_voicemessage", "ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="voicemessage",
            index=models.Index(fields=["sender", "-created_at"], name="vm_sender_recent_idx"),
        ),
    ]
