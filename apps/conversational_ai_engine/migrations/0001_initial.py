from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PersonaContext",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(blank=True, help_text="Job title or function (e.g. 'Senior Backend Engineer').", max_length=200)),
                ("industry", models.CharField(blank=True, help_text="Industry / sector (e.g. 'FinTech, B2B SaaS').", max_length=200)),
                ("expertise", models.TextField(blank=True, help_text="Areas of expertise the AI should lean on.")),
                ("target_audience", models.TextField(blank=True, help_text="Who the generated content speaks to.")),
                ("writing_style", models.TextField(blank=True, help_text="Tone, vocabulary, voice traits.")),
                ("bio", models.TextField(blank=True, help_text="Short bio / description of the author.")),
                ("examples", models.TextField(blank=True, help_text="Example outputs the user likes.")),
                ("additional_context", models.TextField(blank=True, help_text="Any other free-form context.")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(
                    on_delete=models.deletion.CASCADE,
                    related_name="ai_persona",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "db_table": "ai_persona_context",
                "verbose_name": "Persona context",
                "verbose_name_plural": "Persona contexts",
            },
        ),
        migrations.CreateModel(
            name="PromptTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("description", models.TextField(blank=True)),
                ("default_tone", models.CharField(default="professionnel", max_length=32)),
                ("prompt_prefix", models.TextField(blank=True, help_text="Prepended to the user input before the AI call.")),
                ("prompt_suffix", models.TextField(blank=True, help_text="Appended to the user input before the AI call.")),
                ("is_default", models.BooleanField(db_index=True, default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=models.deletion.CASCADE,
                    related_name="ai_templates",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "db_table": "ai_prompt_template",
                "ordering": ("-is_default", "-updated_at"),
            },
        ),
        migrations.AddIndex(
            model_name="prompttemplate",
            index=models.Index(
                fields=["user", "is_default"],
                name="ai_tmpl_user_default_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="prompttemplate",
            constraint=models.UniqueConstraint(
                fields=("user",),
                condition=models.Q(("is_default", True)),
                name="ai_unique_default_template_per_user",
            ),
        ),
        migrations.CreateModel(
            name="Generation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("session_key", models.CharField(blank=True, db_index=True, help_text="Django session key for anonymous trials.", max_length=64)),
                ("input_text", models.TextField()),
                ("output_text", models.TextField()),
                ("tone", models.CharField(default="professionnel", max_length=32)),
                ("provider", models.CharField(blank=True, help_text="Provider key (e.g. 'anthropic', 'openai').", max_length=32)),
                ("model", models.CharField(blank=True, help_text="Model identifier returned by the provider.", max_length=64)),
                ("input_tokens", models.PositiveIntegerField(default=0)),
                ("output_tokens", models.PositiveIntegerField(default=0)),
                ("cost_usd", models.DecimalField(decimal_places=6, default=0, help_text="Estimated cost in USD.", max_digits=10)),
                ("retrieved_memory_ids", models.JSONField(blank=True, default=list, help_text="IDs of RAG chunks injected into the prompt, if any.")),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("template", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=models.deletion.SET_NULL,
                    related_name="generations",
                    to="conversational_ai_engine.prompttemplate",
                )),
                ("user", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=models.deletion.SET_NULL,
                    related_name="ai_generations",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "db_table": "ai_generation",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddIndex(
            model_name="generation",
            index=models.Index(
                fields=["user", "-created_at"],
                name="ai_gen_user_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="generation",
            index=models.Index(
                fields=["session_key", "-created_at"],
                name="ai_gen_session_created_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="generation",
            constraint=models.CheckConstraint(
                check=(
                    models.Q(("user__isnull", False))
                    | ~models.Q(("session_key", ""))
                ),
                name="ai_generation_user_or_session",
            ),
        ),
    ]
