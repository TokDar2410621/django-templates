from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="LegalDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(db_index=True, max_length=48)),
                ("language", models.CharField(db_index=True, default="fr", max_length=8)),
                ("title", models.CharField(help_text="Titre affiché en haut de la page.", max_length=200)),
                ("body_markdown", models.TextField(help_text="Contenu Markdown.")),
                ("effective_from", models.DateTimeField(help_text="Date d'entrée en vigueur officielle de cette version.")),
                ("is_active", models.BooleanField(db_index=True, default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=models.deletion.SET_NULL,
                    related_name="legal_documents_created",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "db_table": "legal_document",
                "ordering": ("kind", "language", "-effective_from"),
            },
        ),
        migrations.AddIndex(
            model_name="legaldocument",
            index=models.Index(
                fields=["kind", "language", "is_active"],
                name="legal_doc_kind_lang_active_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="legaldocument",
            constraint=models.UniqueConstraint(
                fields=("kind", "language"),
                condition=models.Q(("is_active", True)),
                name="legal_unique_active_per_kind_lang",
            ),
        ),
    ]
