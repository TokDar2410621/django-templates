from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Partner",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("display_name", models.CharField(help_text="Public-facing name shown on receipts and dashboards.", max_length=120)),
                ("payout_email", models.EmailField(blank=True, help_text="Email Stripe uses to identify the partner during the OAuth handshake. Defaults to the user's email if blank.", max_length=254)),
                ("stripe_account_id", models.CharField(blank=True, db_index=True, help_text="Stripe account ID (acct_…) once OAuth has linked one.", max_length=100)),
                ("stripe_account_verified", models.BooleanField(db_index=True, default=False, help_text="True once Stripe confirms the account can receive transfers (set by the account.updated webhook or by the OAuth callback).")),
                ("default_share_bps", models.PositiveIntegerField(default=7000, help_text="Default share in basis points. 7000 = 70.00%. The platform keeps the remainder (10000 - share).")),
                ("flat_per_order_cents", models.PositiveIntegerField(default=0, help_text="Optional flat deduction per order item, in cents. Subtracted from the gross BEFORE the share is computed. 0 disables.")),
                ("active", models.BooleanField(default=True, help_text="Uncheck to suspend payouts without deleting the row.")),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.OneToOneField(
                    on_delete=models.deletion.CASCADE,
                    related_name="partner_profile",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "db_table": "scm_partner",
                "ordering": ("display_name",),
                "verbose_name": "Stripe Connect partner",
                "verbose_name_plural": "Stripe Connect partners",
            },
        ),
        migrations.CreateModel(
            name="PartnerProductShare",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("external_product_id", models.CharField(help_text="Identifier from your project's Product model. Could be a UUID, slug, SKU, or external_id — whatever you key by.", max_length=128)),
                ("share_bps", models.PositiveIntegerField(help_text="Override share, in basis points. 7000 = 70.00%.")),
                ("notes", models.CharField(blank=True, help_text="Internal note (reason for the override). Optional.", max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("partner", models.ForeignKey(
                    on_delete=models.deletion.CASCADE,
                    related_name="product_shares",
                    to="stripe_connect_multivendor.partner",
                )),
            ],
            options={
                "db_table": "scm_partner_product_share",
                "ordering": ("partner__display_name", "external_product_id"),
                "verbose_name": "Per-SKU share override",
                "verbose_name_plural": "Per-SKU share overrides",
                "unique_together": {("partner", "external_product_id")},
            },
        ),
        migrations.CreateModel(
            name="Payout",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("external_order_id", models.CharField(db_index=True, max_length=128)),
                ("external_order_item_id", models.CharField(db_index=True, max_length=128)),
                ("gross_cents", models.PositiveIntegerField(help_text="Line gross (in cents) at payout-creation time.")),
                ("share_bps", models.PositiveIntegerField(help_text="Share applied (in basis points) at payout-creation time.")),
                ("partner_amount_cents", models.PositiveIntegerField(help_text="Amount transferred to the partner (in cents).")),
                ("platform_fee_cents", models.PositiveIntegerField(help_text="Amount the platform kept (gross - partner_amount).")),
                ("currency", models.CharField(default="CAD", help_text="ISO 4217 code, uppercase. Stripe expects lowercase at API time.", max_length=8)),
                ("stripe_transfer_id", models.CharField(blank=True, db_index=True, help_text="``tr_xxx`` from Stripe once the transfer succeeds.", max_length=120)),
                ("status", models.CharField(
                    choices=[
                        ("pending", "Pending"),
                        ("paid", "Paid"),
                        ("failed", "Failed"),
                        ("reversed", "Reversed"),
                    ],
                    db_index=True,
                    default="pending",
                    max_length=12,
                )),
                ("error", models.TextField(blank=True, help_text="Last Stripe error message if status == failed.")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                ("partner", models.ForeignKey(
                    help_text="PROTECT: deleting a Partner with payout history is blocked to preserve the financial audit trail. Soft-archive via the ``active`` flag instead.",
                    on_delete=models.deletion.PROTECT,
                    related_name="payouts",
                    to="stripe_connect_multivendor.partner",
                )),
            ],
            options={
                "db_table": "scm_payout",
                "ordering": ("-created_at",),
                "unique_together": {("external_order_item_id", "partner")},
            },
        ),
        migrations.AddIndex(
            model_name="payout",
            index=models.Index(fields=["partner", "status"], name="scm_payout_partner_status_idx"),
        ),
        migrations.AddIndex(
            model_name="payout",
            index=models.Index(fields=["external_order_id", "status"], name="scm_payout_extord_status_idx"),
        ),
        migrations.AddIndex(
            model_name="payout",
            index=models.Index(fields=["paid_at"], name="scm_payout_paid_at_idx"),
        ),
        migrations.CreateModel(
            name="Affiliate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(help_text="Promo code customers enter at checkout (case-insensitive).", max_length=40, unique=True)),
                ("commission_bps", models.PositiveIntegerField(default=1000, help_text="Commission in basis points. 1000 = 10.00% of subtotal.")),
                ("flat_per_order_cents", models.PositiveIntegerField(default=0, help_text="Flat amount per order using the code, in cents. Used when you want a fixed referral fee rather than a percentage. If non-zero, takes priority over ``commission_bps``.")),
                ("stripe_account_id", models.CharField(blank=True, max_length=100)),
                ("stripe_account_verified", models.BooleanField(default=False)),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.OneToOneField(
                    on_delete=models.deletion.CASCADE,
                    related_name="affiliate_profile",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "db_table": "scm_affiliate",
                "ordering": ("code",),
            },
        ),
    ]
