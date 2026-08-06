import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import team_membership_invites.models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Team",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID",
                )),
                ("name", models.CharField(max_length=80)),
                ("slug", models.SlugField(
                    blank=True,
                    help_text="Optional friendly URL identifier (e.g. /teams/acme/).",
                    max_length=80,
                    null=True,
                    unique=True,
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("creator", models.ForeignKey(
                    help_text=(
                        "The user who created the team. PROTECTed so deleting a "
                        "user doesn't orphan their teams — transfer or disband first."
                    ),
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="teams_created",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "db_table": "team_membership_team",
                "ordering": ("-created_at",),
            },
        ),
        migrations.CreateModel(
            name="TeamMember",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID",
                )),
                ("role", models.CharField(
                    choices=[("creator", "Creator"), ("member", "Member")],
                    default="member",
                    help_text=(
                        "Role of the user within this team. The creator's row is "
                        "always 'creator'; everyone else defaults to 'member'."
                    ),
                    max_length=32,
                )),
                ("joined_at", models.DateTimeField(auto_now_add=True)),
                ("team", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="members",
                    to="team_membership_invites.team",
                )),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="team_memberships",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "db_table": "team_membership_member",
                "ordering": ("joined_at",),
            },
        ),
        migrations.CreateModel(
            name="TeamInvite",
            fields=[
                ("id", models.BigAutoField(
                    auto_created=True, primary_key=True, serialize=False, verbose_name="ID",
                )),
                ("email", models.EmailField(
                    help_text="Recipient email. Stored lowercased to dedupe case-variants.",
                    max_length=254,
                )),
                ("token", models.CharField(
                    default=team_membership_invites.models._gen_invite_token,
                    max_length=64,
                    unique=True,
                )),
                ("expires_at", models.DateTimeField(
                    help_text="Hard cutoff after which accept_invite() rejects the token.",
                )),
                ("accepted_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("invited_by", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="team_invites_sent",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("team", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="invites",
                    to="team_membership_invites.team",
                )),
            ],
            options={
                "db_table": "team_membership_invite",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddIndex(
            model_name="teammember",
            index=models.Index(fields=["user", "team"], name="team_member_user_team_idx"),
        ),
        migrations.AddConstraint(
            model_name="teammember",
            constraint=models.UniqueConstraint(
                fields=("team", "user"), name="unique_team_member",
            ),
        ),
        migrations.AddIndex(
            model_name="teaminvite",
            index=models.Index(fields=["team", "email"], name="team_invite_team_email_idx"),
        ),
        migrations.AddIndex(
            model_name="teaminvite",
            index=models.Index(
                fields=["email", "accepted_at", "revoked_at"],
                name="team_invite_email_status_idx",
            ),
        ),
    ]
