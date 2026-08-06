from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ActivationBatch",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        db_index=True,
                        help_text="Distribution channel for this batch.",
                        max_length=32,
                    ),
                ),
                (
                    "tag_format",
                    models.CharField(
                        help_text="Physical form of the tag.", max_length=32,
                    ),
                ),
                (
                    "claim_mode",
                    models.CharField(
                        choices=[
                            ("code", "Code required"),
                            ("photo", "Photo + dispute window"),
                        ],
                        db_index=True,
                        default="code",
                        help_text=(
                            "CODE = a scratch-off carton or sealed envelope ships "
                            "with each tag. PHOTO = no per-tag code; buyer claims "
                            "by uploading a photo (use for supermarket / "
                            "factory-applied)."
                        ),
                        max_length=8,
                    ),
                ),
                (
                    "size",
                    models.PositiveIntegerField(
                        help_text="Number of tags in the batch.",
                    ),
                ),
                ("partner_label", models.CharField(blank=True, default="", max_length=120)),
                ("notes", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="activation_batches",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "activation_batch",
                "ordering": ("-created_at",),
                "verbose_name": "Activation batch",
                "verbose_name_plural": "Activation batches",
            },
        ),
        migrations.CreateModel(
            name="ActivationCode",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "qr_slug",
                    models.CharField(db_index=True, max_length=16, unique=True),
                ),
                (
                    "activation_code",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=16,
                    ),
                ),
                ("consumed_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                (
                    "claim_status",
                    models.CharField(
                        choices=[
                            ("provisional", "Provisional (dispute window open)"),
                            ("confirmed",   "Confirmed (window closed, no dispute)"),
                            ("disputed",    "Disputed (admin review)"),
                        ],
                        db_index=True,
                        default="confirmed",
                        help_text=(
                            "Lifecycle of the claim. Only meaningful for "
                            "PHOTO-mode codes. CODE-mode rows always sit at "
                            "CONFIRMED."
                        ),
                        max_length=12,
                    ),
                ),
                (
                    "provisional_until",
                    models.DateTimeField(
                        blank=True,
                        db_index=True,
                        help_text=(
                            "When the dispute window closes. Set to "
                            "now + ACTIVATION_PROVISIONAL_HOURS at first "
                            "photo-claim; cleared on CONFIRMED. Always null "
                            "for CODE-mode codes."
                        ),
                        null=True,
                    ),
                ),
                (
                    "proof_photo",
                    models.ImageField(
                        blank=True,
                        help_text=(
                            "Photo uploaded by the first claimer (PHOTO mode "
                            "only)."
                        ),
                        null=True,
                        upload_to="activation_codes/proof/",
                    ),
                ),
                ("linked_object_id", models.PositiveBigIntegerField(blank=True, null=True)),
                (
                    "batch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="codes",
                        to="qr_tag_activation_batches.activationbatch",
                    ),
                ),
                (
                    "consumed_by",
                    models.ForeignKey(
                        blank=True,
                        help_text="User who claimed this code.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="activation_codes_consumed",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "linked_object_type",
                    models.ForeignKey(
                        blank=True,
                        help_text="ContentType of the domain object linked at claim time.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="contenttypes.contenttype",
                    ),
                ),
            ],
            options={
                "db_table": "activation_code",
                "ordering": ("-consumed_at", "qr_slug"),
            },
        ),
        migrations.CreateModel(
            name="OwnershipDispute",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "proof_photo",
                    models.ImageField(upload_to="activation_codes/disputes/"),
                ),
                (
                    "claimer_message",
                    models.TextField(blank=True, default="", max_length=2000),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, db_index=True),
                ),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                (
                    "resolved_in_favor_of_claimer",
                    models.BooleanField(blank=True, null=True),
                ),
                (
                    "claimer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ownership_disputes_filed",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "code",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ownership_disputes",
                        to="qr_tag_activation_batches.activationcode",
                    ),
                ),
                (
                    "resolved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="ownership_disputes_resolved",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "activation_ownership_dispute",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddIndex(
            model_name="activationcode",
            index=models.Index(
                fields=["consumed_at"],
                name="activation__consume_b6c2d4_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="activationcode",
            index=models.Index(
                fields=["claim_status", "provisional_until"],
                name="activation__claim_s_8a91f5_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="activationcode",
            constraint=models.UniqueConstraint(
                condition=models.Q(("activation_code__gt", "")),
                fields=("batch", "activation_code"),
                name="actcode_unique_code_per_batch_when_set",
            ),
        ),
        migrations.AddIndex(
            model_name="ownershipdispute",
            index=models.Index(
                fields=["resolved_at"],
                name="activation__resolve_2c3a9b_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="ownershipdispute",
            constraint=models.UniqueConstraint(
                fields=("code", "claimer"),
                name="actcode_unique_dispute_per_claimer",
            ),
        ),
    ]
