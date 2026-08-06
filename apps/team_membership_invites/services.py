"""Team services — create / invite / accept / leave / remove / disband.

All write operations live here so views stay thin and admin actions can
reuse the same code path. Each function is ``@transaction.atomic`` so the
DB never ends up half-mutated if a signal receiver raises.

Errors are raised as ``TeamServiceError`` so the view layer can catch a
single type and convert to a 400/403 response.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import ROLE_CREATOR, ROLE_MEMBER, Team, TeamInvite, TeamMember
from .signals import team_invite_sent, team_member_added, team_member_removed

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configurable behavior
# ---------------------------------------------------------------------------
def _invite_expiry_days() -> int:
    return int(getattr(settings, "TEAM_INVITE_EXPIRY_DAYS", 14))


def _allow_member_invites() -> bool:
    return bool(getattr(settings, "TEAM_ALLOW_MEMBER_INVITES", False))


class TeamServiceError(Exception):
    """Business-rule violation in a team service call.

    Caught by the view layer and converted into a 400 (or 403 for permission
    errors). Keep messages user-facing; they may be shown directly.
    """


class TeamPermissionError(TeamServiceError):
    """Subclass for permission errors → maps to 403 in the view layer."""


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
@transaction.atomic
def create_team(*, creator, name: str, slug: Optional[str] = None) -> Team:
    """Create a Team + the creator's TeamMember row in one transaction.

    The creator is always inserted with role ``creator`` regardless of the
    project's ``TEAM_ROLE_CHOICES`` override (the "creator" string is the
    permission anchor).
    """
    name = (name or "").strip()
    if not name:
        raise TeamServiceError("Team name is required.")
    team = Team.objects.create(name=name[:80], slug=(slug or None), creator=creator)
    TeamMember.objects.create(team=team, user=creator, role=ROLE_CREATOR)
    logger.info("team.created id=%s name=%s by=%s", team.pk, team.name, creator.pk)
    return team


# ---------------------------------------------------------------------------
# Invite
# ---------------------------------------------------------------------------
@transaction.atomic
def invite(*, team: Team, email: str, invited_by) -> TeamInvite:
    """Create a single-use invitation to ``email`` for ``team``.

    Idempotent on (team, email, pending) — returns the existing pending
    row instead of stacking duplicates.

    Permission: by default only the creator can invite. Flip
    ``TEAM_ALLOW_MEMBER_INVITES = True`` to let any member invite.

    Side effect: emits ``team_invite_sent`` AFTER commit — the project's
    notification layer hooks into that signal to send the email.
    """
    email = (email or "").strip().lower()
    if not email:
        raise TeamServiceError("Email is required.")

    # Permission check
    is_creator = team.creator_id == invited_by.id
    is_member = TeamMember.objects.filter(team=team, user=invited_by).exists()
    if not is_member:
        raise TeamPermissionError("You are not a member of this team.")
    if not is_creator and not _allow_member_invites():
        raise TeamPermissionError("Only the team creator can invite new members.")

    # Don't double-invite a pending row.
    existing = TeamInvite.objects.filter(
        team=team,
        email__iexact=email,
        accepted_at__isnull=True,
        revoked_at__isnull=True,
        expires_at__gt=timezone.now(),
    ).first()
    if existing:
        return existing

    # Don't invite an existing member.
    if TeamMember.objects.filter(
        team=team, user__email__iexact=email,
    ).exists():
        raise TeamServiceError("This person is already a team member.")

    expires_at = timezone.now() + timedelta(days=_invite_expiry_days())
    inv = TeamInvite.objects.create(
        team=team,
        invited_by=invited_by,
        email=email,
        expires_at=expires_at,
    )
    logger.info(
        "team.invited team=%s email=%s by=%s token=%s",
        team.pk, email, invited_by.pk, inv.token[:8],
    )

    # Fire AFTER commit so receivers see a row that actually exists in the DB.
    def _emit() -> None:
        team_invite_sent.send(
            sender=TeamInvite,
            instance=inv,
            team=team,
            email=email,
            token=inv.token,
            invited_by=invited_by,
        )

    transaction.on_commit(_emit)
    return inv


# ---------------------------------------------------------------------------
# Accept
# ---------------------------------------------------------------------------
@transaction.atomic
def accept_invite(*, token: str, user) -> TeamMember:
    """Accept an invitation token and create the TeamMember.

    Single-use: the row is locked with ``select_for_update`` so two
    concurrent clicks on the same email's invite link can't both win.

    Email match is enforced softly: the invite must have been sent to the
    same email as the accepting user. Without this check, leaking a token
    would let an attacker join any team — see the email confirmation note in
    the README for what to add on top in your project.
    """
    token = (token or "").strip()
    if not token:
        raise TeamServiceError("Token is required.")

    try:
        inv = TeamInvite.objects.select_for_update().get(token=token)
    except TeamInvite.DoesNotExist as exc:
        raise TeamServiceError("Invitation not found.") from exc

    if inv.accepted_at is not None:
        raise TeamServiceError("Invitation already accepted.")
    if inv.revoked_at is not None:
        raise TeamServiceError("Invitation has been revoked.")
    if inv.expires_at <= timezone.now():
        raise TeamServiceError("Invitation has expired.")

    user_email = (getattr(user, "email", "") or "").lower()
    if inv.email.lower() != user_email:
        raise TeamServiceError(
            "This invitation was sent to a different email address."
        )

    member, created = TeamMember.objects.get_or_create(
        team=inv.team, user=user, defaults={"role": ROLE_MEMBER},
    )
    inv.accepted_at = timezone.now()
    inv.save(update_fields=["accepted_at"])
    logger.info(
        "team.invite_accepted team=%s user=%s token=%s created=%s",
        inv.team_id, user.pk, inv.token[:8], created,
    )

    if created:
        def _emit() -> None:
            team_member_added.send(
                sender=TeamMember, instance=member, team=inv.team, user=user,
            )
        transaction.on_commit(_emit)

    return member


# ---------------------------------------------------------------------------
# Revoke
# ---------------------------------------------------------------------------
@transaction.atomic
def revoke_invite(*, token: str, by) -> None:
    """Cancel a pending invitation. Any team member can revoke.

    No-op if the invite is already accepted or revoked.
    """
    try:
        inv = TeamInvite.objects.select_for_update().get(token=token)
    except TeamInvite.DoesNotExist as exc:
        raise TeamServiceError("Invitation not found.") from exc
    if not TeamMember.objects.filter(team=inv.team, user=by).exists():
        raise TeamPermissionError("You are not a member of this team.")
    if inv.accepted_at is not None or inv.revoked_at is not None:
        return
    inv.revoked_at = timezone.now()
    inv.save(update_fields=["revoked_at"])
    logger.info("team.invite_revoked team=%s by=%s token=%s", inv.team_id, by.pk, inv.token[:8])


# ---------------------------------------------------------------------------
# Leave / Remove / Disband
# ---------------------------------------------------------------------------
@transaction.atomic
def leave_team(*, team: Team, user) -> None:
    """Remove yourself from a team.

    The creator can't simply leave — they must ``disband`` the team or
    (in a future-work extension) transfer ownership first. This avoids
    orphaning the PROTECTed creator FK.
    """
    if team.creator_id == user.id:
        raise TeamServiceError(
            "The creator cannot leave the team; disband or transfer ownership first."
        )
    deleted, _ = TeamMember.objects.filter(team=team, user=user).delete()
    if deleted == 0:
        raise TeamServiceError("You are not a member of this team.")
    logger.info("team.left team=%s user=%s", team.pk, user.pk)

    def _emit() -> None:
        team_member_removed.send(
            sender=TeamMember, team=team, user=user, removed_by=user, was_self_leave=True,
        )
    transaction.on_commit(_emit)


@transaction.atomic
def remove_member(*, team: Team, user, by) -> None:
    """Kick another member. Only the creator may do this.

    Removing the creator is forbidden — they must disband the team first.
    """
    if team.creator_id != by.id:
        raise TeamPermissionError("Only the team creator can remove members.")
    if user.id == team.creator_id:
        raise TeamServiceError("The creator cannot be removed; disband the team instead.")
    deleted, _ = TeamMember.objects.filter(team=team, user=user).delete()
    if deleted == 0:
        raise TeamServiceError("That user is not a member of this team.")
    logger.info("team.member_removed team=%s user=%s by=%s", team.pk, user.pk, by.pk)

    def _emit() -> None:
        team_member_removed.send(
            sender=TeamMember, team=team, user=user, removed_by=by, was_self_leave=False,
        )
    transaction.on_commit(_emit)


@transaction.atomic
def disband(*, team: Team, by) -> None:
    """Delete the team entirely. Only the creator may do this.

    Cascades to TeamMember and TeamInvite rows. Domain-side FKs that
    reference Team should be declared with ``on_delete=SET_NULL`` if you
    want the underlying records to survive the team's dissolution.
    """
    if team.creator_id != by.id:
        raise TeamPermissionError("Only the team creator can disband the team.")
    team_id, name = team.pk, team.name
    team.delete()
    logger.info("team.disbanded id=%s name=%s by=%s", team_id, name, by.pk)
