from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Subscription",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("plan", models.CharField(default="free", max_length=32, help_text="Plan slug. Must match a key in SAAS_PLAN_LIMITS.")),
                ("status", models.CharField(default="active", max_length=20, help_text="Mirror of Stripe Subscription.status.")),
                ("stripe_customer_id", models.CharField(blank=True, db_index=True, default="", max_length=120, help_text="Stripe Customer.id (cus_xxx). Set on first checkout.")),
                ("stripe_subscription_id", models.CharField(blank=True, default="", max_length=120, help_text="Stripe Subscription.id (sub_xxx). Empty for free plan.")),
                ("current_period_end", models.DateTimeField(blank=True, null=True, help_text="When Stripe will charge the next renewal. NULL on free plan.")),
                ("cancel_at_period_end", models.BooleanField(default=False, help_text="True after the user clicked 'Cancel' but the current billing period hasn't ended yet.")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(
                    on_delete=models.deletion.CASCADE,
                    related_name="subscription",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "db_table": "saas_subscription",
                "ordering": ("-updated_at",),
            },
        ),
        migrations.AddIndex(
            model_name="subscription",
            index=models.Index(
                fields=["stripe_customer_id"],
                name="saas_sub_customer_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="subscription",
            index=models.Index(
                fields=["plan", "status"],
                name="saas_sub_plan_status_idx",
            ),
        ),
        migrations.CreateModel(
            name="CreditBalance",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("balance", models.PositiveIntegerField(default=0, help_text="Current credit balance. Always non-negative — debit is atomic with a balance__gte=amount filter.")),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(
                    on_delete=models.deletion.CASCADE,
                    related_name="credit_balance",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "db_table": "saas_credit_balance",
                "ordering": ("-updated_at",),
            },
        ),
        migrations.CreateModel(
            name="CreditTransaction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.IntegerField(help_text="Positive for credits added, negative for spent. Signed so the running balance = SUM(amount).")),
                ("kind", models.CharField(max_length=20)),
                ("resource_key", models.CharField(blank=True, db_index=True, default="", max_length=64, help_text="For 'spend' txns, the resource that was billed (e.g. 'article_generation'). Empty for purchase/refund/gift.")),
                ("stripe_session_id", models.CharField(blank=True, db_index=True, default="", max_length=120, help_text="Stripe Checkout Session id for purchase events. Used as idempotency key — duplicate webhooks are NO-OP.")),
                ("description", models.CharField(blank=True, default="", max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(
                    on_delete=models.deletion.CASCADE,
                    related_name="credit_transactions",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "db_table": "saas_credit_transaction",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddIndex(
            model_name="credittransaction",
            index=models.Index(
                fields=["user", "-created_at"],
                name="saas_txn_user_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="credittransaction",
            index=models.Index(
                fields=["kind", "-created_at"],
                name="saas_txn_kind_created_idx",
            ),
        ),
        migrations.CreateModel(
            name="MonthlyQuota",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("resource_key", models.CharField(db_index=True, max_length=64, help_text="Resource identifier matching keys in SAAS_PLAN_LIMITS (e.g. 'article_generation', 'api_call', 'export').")),
                ("month_key", models.CharField(db_index=True, max_length=7, help_text="YYYY-MM. Generated by services.current_month_key() — override if you need billing-cycle months.")),
                ("count", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(
                    on_delete=models.deletion.CASCADE,
                    related_name="monthly_quotas",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "db_table": "saas_monthly_quota",
                "ordering": ("-month_key", "resource_key"),
            },
        ),
        migrations.AddConstraint(
            model_name="monthlyquota",
            constraint=models.UniqueConstraint(
                fields=("user", "resource_key", "month_key"),
                name="saas_quota_unique_user_resource_month",
            ),
        ),
        migrations.AddIndex(
            model_name="monthlyquota",
            index=models.Index(
                fields=["user", "resource_key", "month_key"],
                name="saas_quota_user_resource_idx",
            ),
        ),
    ]
