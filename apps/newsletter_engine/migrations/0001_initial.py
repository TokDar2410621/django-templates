"""Initial schema for newsletter_engine.

Hand-written rather than generated so the template ships ready-to-migrate
without depending on the consumer project's settings being in place at
makemigrations time. Consumers can ``makemigrations newsletter_engine
--empty`` later if they need to evolve the schema.
"""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def _tenant_target() -> str:
    return getattr(settings, "NEWSLETTER_TENANT_MODEL", settings.AUTH_USER_MODEL)


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # -------------------------------------------------------------------
        # Subscriber
        # -------------------------------------------------------------------
        migrations.CreateModel(
            name="Subscriber",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("email", models.EmailField(db_index=True, max_length=254)),
                ("name", models.CharField(blank=True, default="", max_length=120)),
                ("status", models.CharField(
                    choices=[
                        ("pending", "Pending confirmation"),
                        ("confirmed", "Confirmed"),
                        ("unsubscribed", "Unsubscribed"),
                        ("bounced", "Bounced (hard)"),
                        ("complained", "Spam complaint"),
                    ],
                    db_index=True, default="pending", max_length=20,
                )),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("unsubscribed_at", models.DateTimeField(blank=True, null=True)),
                ("source", models.CharField(blank=True, default="", max_length=50)),
                ("consented_marketing", models.BooleanField(default=False)),
                ("locale", models.CharField(default="fr", max_length=10)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("bounce_count", models.PositiveIntegerField(default=0)),
                ("last_bounce_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("tenant", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="newsletter_subscribers",
                    to=_tenant_target(),
                )),
            ],
            options={
                "db_table": "newsletter_subscriber",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddConstraint(
            model_name="subscriber",
            constraint=models.UniqueConstraint(
                fields=("tenant", "email"),
                name="newsletter_unique_subscriber_per_tenant",
            ),
        ),
        migrations.AddIndex(
            model_name="subscriber",
            index=models.Index(fields=["tenant", "email"], name="nl_sub_tenant_email_idx"),
        ),
        migrations.AddIndex(
            model_name="subscriber",
            index=models.Index(fields=["tenant", "status"], name="nl_sub_tenant_status_idx"),
        ),
        migrations.AddIndex(
            model_name="subscriber",
            index=models.Index(fields=["tenant", "-created_at"], name="nl_sub_tenant_created_idx"),
        ),

        # -------------------------------------------------------------------
        # MailingList
        # -------------------------------------------------------------------
        migrations.CreateModel(
            name="MailingList",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("slug", models.SlugField(max_length=80)),
                ("description", models.TextField(blank=True, default="")),
                ("is_active", models.BooleanField(default=True)),
                ("default_from_role", models.CharField(default="newsletter", max_length=32)),
                ("default_reply_to", models.EmailField(blank=True, default="", max_length=254)),
                ("requires_double_opt_in", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("tenant", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="newsletter_lists",
                    to=_tenant_target(),
                )),
            ],
            options={
                "db_table": "newsletter_list",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddConstraint(
            model_name="mailinglist",
            constraint=models.UniqueConstraint(
                fields=("tenant", "slug"),
                name="newsletter_unique_list_slug_per_tenant",
            ),
        ),
        migrations.AddIndex(
            model_name="mailinglist",
            index=models.Index(fields=["tenant", "slug"], name="nl_list_tenant_slug_idx"),
        ),

        # -------------------------------------------------------------------
        # Membership
        # -------------------------------------------------------------------
        migrations.CreateModel(
            name="Membership",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(
                    choices=[("active", "Active"), ("unsubscribed", "Unsubscribed")],
                    db_index=True, default="active", max_length=20,
                )),
                ("subscribed_at", models.DateTimeField(auto_now_add=True)),
                ("unsubscribed_at", models.DateTimeField(blank=True, null=True)),
                ("unsubscribe_reason", models.CharField(blank=True, default="", max_length=200)),
                ("list", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="memberships",
                    to="newsletter_engine.mailinglist",
                )),
                ("subscriber", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="memberships",
                    to="newsletter_engine.subscriber",
                )),
            ],
            options={
                "db_table": "newsletter_membership",
                "ordering": ("-subscribed_at",),
            },
        ),
        migrations.AddConstraint(
            model_name="membership",
            constraint=models.UniqueConstraint(
                fields=("subscriber", "list"),
                name="newsletter_unique_membership",
            ),
        ),
        migrations.AddIndex(
            model_name="membership",
            index=models.Index(fields=["list", "status"], name="nl_membership_list_status_idx"),
        ),
        migrations.AddIndex(
            model_name="membership",
            index=models.Index(fields=["subscriber", "status"], name="nl_membership_sub_status_idx"),
        ),

        # -------------------------------------------------------------------
        # Tag + SubscriberTag
        # -------------------------------------------------------------------
        migrations.CreateModel(
            name="Tag",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=80)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("tenant", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="newsletter_tags",
                    to=_tenant_target(),
                )),
            ],
            options={
                "db_table": "newsletter_tag",
                "ordering": ("name",),
            },
        ),
        migrations.AddConstraint(
            model_name="tag",
            constraint=models.UniqueConstraint(
                fields=("tenant", "name"),
                name="newsletter_unique_tag_per_tenant",
            ),
        ),
        migrations.CreateModel(
            name="SubscriberTag",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("subscriber", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="subscriber_tags",
                    to="newsletter_engine.subscriber",
                )),
                ("tag", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="subscriber_tags",
                    to="newsletter_engine.tag",
                )),
            ],
            options={"db_table": "newsletter_subscriber_tag"},
        ),
        migrations.AddConstraint(
            model_name="subscribertag",
            constraint=models.UniqueConstraint(
                fields=("subscriber", "tag"),
                name="newsletter_unique_subscriber_tag",
            ),
        ),
        migrations.AddIndex(
            model_name="subscribertag",
            index=models.Index(fields=["tag", "subscriber"], name="nl_subtag_tag_sub_idx"),
        ),

        # -------------------------------------------------------------------
        # Segment
        # -------------------------------------------------------------------
        migrations.CreateModel(
            name="Segment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("filters", models.JSONField(blank=True, default=dict)),
                ("subscriber_count", models.PositiveIntegerField(default=0)),
                ("last_evaluated_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("list", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="segments",
                    to="newsletter_engine.mailinglist",
                )),
                ("tenant", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="newsletter_segments",
                    to=_tenant_target(),
                )),
            ],
            options={
                "db_table": "newsletter_segment",
                "ordering": ("-updated_at",),
            },
        ),
        migrations.AddIndex(
            model_name="segment",
            index=models.Index(fields=["tenant", "-updated_at"], name="nl_seg_tenant_updated_idx"),
        ),

        # -------------------------------------------------------------------
        # Campaign
        # -------------------------------------------------------------------
        migrations.CreateModel(
            name="Campaign",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("subject", models.CharField(max_length=255)),
                ("html_body", models.TextField()),
                ("text_body", models.TextField(blank=True, default="")),
                ("status", models.CharField(
                    choices=[
                        ("draft", "Draft"),
                        ("scheduled", "Scheduled"),
                        ("sending", "Sending"),
                        ("sent", "Sent"),
                        ("cancelled", "Cancelled"),
                        ("failed", "Failed"),
                    ],
                    db_index=True, default="draft", max_length=20,
                )),
                ("scheduled_at", models.DateTimeField(blank=True, null=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("from_role", models.CharField(blank=True, default="", max_length=32)),
                ("from_email_override", models.EmailField(blank=True, default="", max_length=254)),
                ("reply_to", models.EmailField(blank=True, default="", max_length=254)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("sent_count", models.PositiveIntegerField(default=0)),
                ("delivered_count", models.PositiveIntegerField(default=0)),
                ("open_count", models.PositiveIntegerField(default=0)),
                ("click_count", models.PositiveIntegerField(default=0)),
                ("bounce_count", models.PositiveIntegerField(default=0)),
                ("unsubscribe_count", models.PositiveIntegerField(default=0)),
                ("complaint_count", models.PositiveIntegerField(default=0)),
                ("created_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="newsletter_campaigns_created",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("list", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="campaigns",
                    to="newsletter_engine.mailinglist",
                )),
                ("segment", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="campaigns",
                    to="newsletter_engine.segment",
                )),
                ("tenant", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="newsletter_campaigns",
                    to=_tenant_target(),
                )),
            ],
            options={
                "db_table": "newsletter_campaign",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddConstraint(
            model_name="campaign",
            constraint=models.CheckConstraint(
                check=(
                    (models.Q(list__isnull=False) & models.Q(segment__isnull=True))
                    | (models.Q(list__isnull=True) & models.Q(segment__isnull=False))
                ),
                name="newsletter_campaign_list_xor_segment",
            ),
        ),
        migrations.AddIndex(
            model_name="campaign",
            index=models.Index(fields=["tenant", "-created_at"], name="nl_camp_tenant_created_idx"),
        ),
        migrations.AddIndex(
            model_name="campaign",
            index=models.Index(fields=["status", "scheduled_at"], name="nl_camp_status_sched_idx"),
        ),

        # -------------------------------------------------------------------
        # Delivery
        # -------------------------------------------------------------------
        migrations.CreateModel(
            name="Delivery",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(
                    choices=[
                        ("pending", "Pending"),
                        ("queued", "Queued"),
                        ("sent", "Sent"),
                        ("delivered", "Delivered"),
                        ("opened", "Opened"),
                        ("clicked", "Clicked"),
                        ("bounced", "Bounced"),
                        ("complained", "Complained"),
                        ("failed", "Failed"),
                        ("skipped", "Skipped"),
                    ],
                    db_index=True, default="pending", max_length=20,
                )),
                ("tracking_token", models.CharField(db_index=True, max_length=64, unique=True)),
                ("provider_message_id", models.CharField(blank=True, default="", max_length=255)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("delivered_at", models.DateTimeField(blank=True, null=True)),
                ("opened_at", models.DateTimeField(blank=True, null=True)),
                ("open_count", models.PositiveIntegerField(default=0)),
                ("last_opened_at", models.DateTimeField(blank=True, null=True)),
                ("clicked_at", models.DateTimeField(blank=True, null=True)),
                ("click_count", models.PositiveIntegerField(default=0)),
                ("last_clicked_at", models.DateTimeField(blank=True, null=True)),
                ("bounced_at", models.DateTimeField(blank=True, null=True)),
                ("error", models.TextField(blank=True, default="")),
                ("campaign", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="deliveries",
                    to="newsletter_engine.campaign",
                )),
                ("subscriber", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="deliveries",
                    to="newsletter_engine.subscriber",
                )),
            ],
            options={
                "db_table": "newsletter_delivery",
                "ordering": ("-id",),
            },
        ),
        migrations.AddConstraint(
            model_name="delivery",
            constraint=models.UniqueConstraint(
                fields=("campaign", "subscriber"),
                name="newsletter_unique_delivery",
            ),
        ),
        migrations.AddIndex(
            model_name="delivery",
            index=models.Index(fields=["campaign", "status"], name="nl_delivery_camp_status_idx"),
        ),
        migrations.AddIndex(
            model_name="delivery",
            index=models.Index(fields=["subscriber", "-id"], name="nl_delivery_sub_id_idx"),
        ),

        # -------------------------------------------------------------------
        # LinkClick
        # -------------------------------------------------------------------
        migrations.CreateModel(
            name="LinkClick",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("original_url", models.URLField(max_length=2000)),
                ("clicked_at", models.DateTimeField(auto_now_add=True)),
                ("user_agent", models.CharField(blank=True, default="", max_length=400)),
                ("ip", models.GenericIPAddressField(blank=True, null=True)),
                ("delivery", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="link_clicks",
                    to="newsletter_engine.delivery",
                )),
            ],
            options={
                "db_table": "newsletter_link_click",
                "ordering": ("-clicked_at",),
            },
        ),
        migrations.AddIndex(
            model_name="linkclick",
            index=models.Index(fields=["delivery", "-clicked_at"], name="nl_linkclick_del_time_idx"),
        ),

        # -------------------------------------------------------------------
        # Automation + steps + enrollment
        # -------------------------------------------------------------------
        migrations.CreateModel(
            name="Automation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("trigger", models.CharField(default="manual", max_length=40)),
                ("trigger_config", models.JSONField(blank=True, default=dict)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("tenant", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="newsletter_automations",
                    to=_tenant_target(),
                )),
            ],
            options={
                "db_table": "newsletter_automation",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddIndex(
            model_name="automation",
            index=models.Index(
                fields=["tenant", "trigger", "is_active"],
                name="nl_auto_tenant_trig_idx",
            ),
        ),
        migrations.CreateModel(
            name="AutomationStep",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("order", models.PositiveIntegerField()),
                ("delay_seconds", models.PositiveIntegerField(default=0)),
                ("subject", models.CharField(max_length=255)),
                ("html_body", models.TextField()),
                ("text_body", models.TextField(blank=True, default="")),
                ("condition", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("automation", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="steps",
                    to="newsletter_engine.automation",
                )),
            ],
            options={
                "db_table": "newsletter_automation_step",
                "ordering": ("automation", "order"),
            },
        ),
        migrations.AddConstraint(
            model_name="automationstep",
            constraint=models.UniqueConstraint(
                fields=("automation", "order"),
                name="newsletter_unique_step_order",
            ),
        ),
        migrations.CreateModel(
            name="AutomationEnrollment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("last_step_index", models.IntegerField(default=-1)),
                ("last_step_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("cancelled_at", models.DateTimeField(blank=True, null=True)),
                ("cancellation_reason", models.CharField(blank=True, default="", max_length=200)),
                ("automation", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="enrollments",
                    to="newsletter_engine.automation",
                )),
                ("subscriber", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="automation_enrollments",
                    to="newsletter_engine.subscriber",
                )),
            ],
            options={
                "db_table": "newsletter_automation_enrollment",
                "ordering": ("-started_at",),
            },
        ),
        migrations.AddConstraint(
            model_name="automationenrollment",
            constraint=models.UniqueConstraint(
                fields=("automation", "subscriber"),
                name="newsletter_unique_enrollment",
            ),
        ),
        migrations.AddIndex(
            model_name="automationenrollment",
            index=models.Index(
                fields=["automation", "completed_at", "cancelled_at"],
                name="nl_enroll_status_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="automationenrollment",
            index=models.Index(fields=["last_step_at"], name="nl_enroll_last_step_idx"),
        ),

        # -------------------------------------------------------------------
        # UnsubscribeToken + BounceEvent
        # -------------------------------------------------------------------
        migrations.CreateModel(
            name="UnsubscribeToken",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token", models.CharField(db_index=True, max_length=96, unique=True)),
                ("scope", models.CharField(default="all", max_length=120)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("used_at", models.DateTimeField(blank=True, null=True)),
                ("subscriber", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="unsubscribe_tokens",
                    to="newsletter_engine.subscriber",
                )),
            ],
            options={
                "db_table": "newsletter_unsubscribe_token",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddIndex(
            model_name="unsubscribetoken",
            index=models.Index(fields=["subscriber", "scope"], name="nl_token_sub_scope_idx"),
        ),
        migrations.CreateModel(
            name="BounceEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(
                    choices=[
                        ("hard", "Hard bounce"),
                        ("soft", "Soft bounce"),
                        ("complaint", "Spam complaint"),
                        ("unsubscribe_webhook", "Unsubscribe (provider webhook)"),
                    ],
                    db_index=True, max_length=32,
                )),
                ("provider_message_id", models.CharField(blank=True, default="", max_length=255)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("subscriber", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="bounce_events",
                    to="newsletter_engine.subscriber",
                )),
            ],
            options={
                "db_table": "newsletter_bounce_event",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddIndex(
            model_name="bounceevent",
            index=models.Index(fields=["subscriber", "-created_at"], name="nl_bounce_sub_time_idx"),
        ),
    ]
