"""Team / group membership with email-based invitations.

A ``Team`` groups several users who share access to some domain object in
your project (a workspace, a project, a co-owned record, etc.). The template
does NOT model the link to your domain object — see README.md for how to
add a ``team = FK(Team, null=True)`` column on your own model.

Model:
- A team is created by one user (the ``creator``); membership is otherwise
  flat (everyone has the same view rights).
- Invitations are email-based: the invitee may not have an account yet. The
  token is generated with ``secrets.token_urlsafe(24)`` and is single-use.
- The default permission model says: only the creator can invite, remove
  others, and disband; any member can leave on their own. Flip
  ``TEAM_ALLOW_MEMBER_INVITES = True`` in settings to let members invite.

Why ``on_delete=PROTECT`` on creator: deleting a user shouldn't silently
orphan or cascade-delete every team they started. Force the operator to
transfer ownership first (a future-work hook), then delete.
"""
from __future__ import annotations

import secrets

from django.conf import settings
from django.db import models


# ---------------------------------------------------------------------------
# Configurable choices
#
# Override in your project's settings:
#
#   TEAM_ROLE_CHOICES = [
#       ("creator", "Creator"),
#       ("admin",   "Admin"),
#       ("member",  "Member"),
#   ]
#
# Defaults below cover the most common case (flat membership).
# ---------------------------------------------------------------------------
ROLE_CREATOR = "creator"
ROLE_MEMBER = "member"

DEFAULT_ROLE_CHOICES: list[tuple[str, str]] = [
    (ROLE_CREATOR, "Creator"),
    (ROLE_MEMBER, "Member"),
]


def _role_choices() -> list[tuple[str, str]]:
    return list(getattr(settings, "TEAM_ROLE_CHOICES", DEFAULT_ROLE_CHOICES))


def _gen_invite_token() -> str:
    """Single-use opaque invite token. 24 URL-safe bytes ≈ 32 chars.

    Long enough that brute-forcing the namespace is infeasible without rate
    limiting; short enough that the email link stays readable.
    """
    return secrets.token_urlsafe(24)


class Team(models.Model):
    """A group of users that share access to something in your domain.

    The model deliberately stays free of any FK back into your project: link
    your own models to ``Team`` via a nullable FK on YOUR side
    (``team = models.ForeignKey(Team, null=True, blank=True, on_delete=models.SET_NULL)``).
    """

    name = models.CharField(max_length=80)
    slug = models.SlugField(
        max_length=80,
        unique=True,
        null=True,
        blank=True,
        help_text="Optional friendly URL identifier (e.g. /teams/acme/).",
    )
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="teams_created",
        help_text="The user who created the team. PROTECTed so deleting a "
        "user doesn't orphan their teams — transfer or disband first.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "team_membership_team"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.name


class TeamMember(models.Model):
    """Many-to-many: User <-> Team with extra metadata (role, joined_at).

    Roles default to ``creator`` / ``member`` (flat). Override
    ``TEAM_ROLE_CHOICES`` in settings if you need finer-grained roles like
    ``admin`` or ``viewer`` — no migration needed since the column is a
    CharField(max_length=32).
    """

    team = models.ForeignKey(
        Team, on_delete=models.CASCADE, related_name="members",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="team_memberships",
    )
    role = models.CharField(
        max_length=32,
        choices=_role_choices(),
        default=ROLE_MEMBER,
        help_text="Role of the user within this team. The creator's row is "
        "always 'creator'; everyone else defaults to 'member'.",
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "team_membership_member"
        ordering = ("joined_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["team", "user"], name="unique_team_member",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "team"]),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} in team {self.team_id} ({self.role})"


class TeamInvite(models.Model):
    """Outstanding invitation by email — accepted by clicking a tokenized link.

    Tokens are single-use: ``accept_invite`` flips ``accepted_at`` to ``now``
    in the same transaction as the ``TeamMember`` insert, so even a
    concurrent click can't double-accept.

    The invitee_email is stored in lowercase to keep ``__iexact`` lookups
    cheap and prevent a malicious case-variant from bypassing the
    "is this person already a member?" check.
    """

    team = models.ForeignKey(
        Team, on_delete=models.CASCADE, related_name="invites",
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="team_invites_sent",
    )
    email = models.EmailField(
        help_text="Recipient email. Stored lowercased to dedupe case-variants.",
    )
    token = models.CharField(
        max_length=64, unique=True, default=_gen_invite_token,
    )
    expires_at = models.DateTimeField(
        help_text="Hard cutoff after which accept_invite() rejects the token.",
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "team_membership_invite"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["team", "email"]),
            models.Index(fields=["email", "accepted_at", "revoked_at"]),
        ]

    def __str__(self) -> str:
        return f"Invite {self.email} → team {self.team_id}"

    @property
    def is_pending(self) -> bool:
        """True iff the invite can still be accepted right now."""
        from django.utils import timezone

        return (
            self.accepted_at is None
            and self.revoked_at is None
            and self.expires_at > timezone.now()
        )
