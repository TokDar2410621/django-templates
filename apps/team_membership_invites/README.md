# team-membership-invites

═════════════════════════════════════════════
Template : team-membership-invites
Version  : 1.0.0
Mode     : EXTRACT-A
Source   : FIN/apps/families
Stack    : Django 5+ / DRF / (unfold optional)
Deps     : `djangorestframework`
Used by  : (none yet)
═════════════════════════════════════════════

A reusable team/group membership module with email-based invitations.
A `Team` groups multiple users who share access to *something* in your
domain; this module owns the team, the memberships, and the invite flow,
and stays decoupled from whatever it is they share.

## Why this template

- **Email-based invites before the account exists.** The invitee doesn't
  need to have signed up — the invitation row stores an email + opaque
  token, and `accept_invite()` later requires the accepting user to have
  the same email.
- **Single-use, expiring tokens.** `secrets.token_urlsafe(24)` (≈32 chars,
  brute-force-infeasible) + a configurable expiry. Double-accept is
  rejected via `SELECT FOR UPDATE` inside the same transaction as the
  `TeamMember` insert.
- **`on_delete=PROTECT` on the creator.** Deleting a user shouldn't
  silently orphan their teams — the operator has to disband or transfer
  ownership first. (Ownership transfer is a future-work hook; see
  "Extending" below.)
- **Service-layer permissions.** All write operations route through
  `services.py`, where the rules live. Views and admin actions reuse the
  same code path, so a permission bug can't appear in only one of them.
- **Configurable knobs without a migration.** Role choices, invite
  expiry, and member-invite policy are all settings.
- **Signal-based notification hand-off.** The template never sends an
  email itself; it fires `team_invite_sent` after commit and lets the
  project's notification layer hook in.

## API

All endpoints are JWT/session-authenticated. Pending invites returned in
the Team payload are visible **only to the team creator**.

| Method | Path                                            | Body                | Purpose                             |
|--------|-------------------------------------------------|---------------------|-------------------------------------|
| GET    | `/api/teams/`                                   | —                   | List teams the caller belongs to    |
| POST   | `/api/teams/`                                   | `{name, slug?}`     | Create a team                       |
| GET    | `/api/teams/<id>/`                              | —                   | Team detail (members + invites)     |
| DELETE | `/api/teams/<id>/`                              | —                   | Disband (creator only)              |
| POST   | `/api/teams/<id>/disband/`                      | —                   | Disband (alias of DELETE)           |
| GET    | `/api/teams/<id>/members/`                      | —                   | List members                        |
| POST   | `/api/teams/<id>/invite/`                       | `{email}`           | Send an invitation                  |
| POST   | `/api/teams/<id>/leave/`                        | —                   | Leave (creator can't)               |
| POST   | `/api/teams/<id>/members/<user_id>/remove/`     | —                   | Remove a member (creator only)      |
| POST   | `/api/teams/accept/`                            | `{token}`           | Accept an invitation                |
| POST   | `/api/teams/invites/<token>/revoke/`            | —                   | Revoke a pending invitation         |
| GET    | `/api/teams/invites/pending/`                   | —                   | List my outstanding invites         |

## Quickstart

```bash
pip install djangorestframework
```

Add to `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    # ...
    "rest_framework",
    "team_membership_invites",
]
```

Wire URLs:

```python
# config/urls.py
urlpatterns = [
    # ...
    path("api/teams/", include("team_membership_invites.urls")),
]
```

Migrate:

```bash
python manage.py migrate
```

See [SETTINGS.md](./SETTINGS.md) for the full configuration matrix.

## Linking to your domain models

The template stores teams, members and invites — but NOT what the team
shares. To link a team to your project's domain object, add a nullable FK
**on YOUR model**:

```python
# your_app/models.py
from team_membership_invites.models import Team


class Workspace(models.Model):
    name = models.CharField(max_length=120)
    team = models.ForeignKey(
        Team,
        null=True, blank=True,
        on_delete=models.SET_NULL,   # team gets disbanded -> workspace survives
        related_name="workspaces",
    )
```

Then for an access check:

```python
from team_membership_invites.selectors import is_member

def can_access(workspace, user) -> bool:
    if workspace.team_id is None:
        return workspace.owner_id == user.id  # or whatever your single-user rule is
    return is_member(workspace.team, user)
```

If you need "all users who can see this object", roll your own helper that
unions `owner_id` with `TeamMember.objects.filter(team=obj.team)
.values_list("user_id", flat=True)`.

## Sending the invitation email

The module deliberately does NOT call your email transport. Instead, it
emits a `team_invite_sent` signal after commit. Hook it up from your
notification layer (e.g. the `notifications-multichannel` template):

```python
# your_app/signals.py
from django.dispatch import receiver
from django.conf import settings

from team_membership_invites.signals import team_invite_sent
# from notifications_multichannel.services import send_email


@receiver(team_invite_sent)
def email_team_invite(sender, instance, team, email, token, invited_by, **kwargs):
    url_template = getattr(
        settings,
        "TEAM_INVITE_URL_TEMPLATE",
        "/teams/accept?token={token}",
    )
    invite_url = url_template.format(token=token)
    # send_email(
    #     to=email,
    #     subject=f"You've been invited to {team.name}",
    #     html=render_to_string("emails/team_invite.html", {
    #         "team": team,
    #         "invited_by": invited_by,
    #         "invite_url": invite_url,
    #     }),
    # )
```

Available signals:

| Signal                  | When                                  | kwargs                                                |
|-------------------------|---------------------------------------|-------------------------------------------------------|
| `team_invite_sent`      | After a `TeamInvite` row is created   | `instance, team, email, token, invited_by`            |
| `team_member_added`     | After `accept_invite()` succeeds      | `instance, team, user`                                |
| `team_member_removed`   | After leave / remove                  | `team, user, removed_by, was_self_leave`              |

## Testing

```bash
pytest apps/team_membership_invites/tests/
```

The test suite covers:

- `test_create.py` — team creation, slug, member-of listing
- `test_invite.py` — invite, dedupe, accept, double-accept reject,
  expired reject, revoke, email mismatch
- `test_permissions.py` — only creator can invite (by default) / remove /
  disband; anyone can leave; creator can't leave

## Customization hooks

- `TEAM_ROLE_CHOICES` — list[(value, label)] of role values stored in
  `TeamMember.role`. Default: `[("creator", "Creator"), ("member",
  "Member")]`. The string `"creator"` is the permission anchor, don't
  rename it.
- `TEAM_INVITE_EXPIRY_DAYS` — default 14
- `TEAM_ALLOW_MEMBER_INVITES` — default `False`. If `True`, any member can
  invite (instead of creator-only).
- `TEAM_INVITE_URL_TEMPLATE` — string with `{token}` placeholder, used by
  YOUR signal receiver to build the accept URL.

## Extending

- **Ownership transfer.** Not in v1.0 — `creator` is `PROTECT`ed, so to
  transfer ownership you currently have to (1) add an admin member, (2)
  flip `team.creator` directly, (3) update the old creator's
  `TeamMember.role`. A future-work `transfer_ownership(team, new_creator,
  by)` service is the right place for this.
- **Per-team settings.** If your project needs per-team toggles
  (notification preferences, branding, etc.), add a separate
  `TeamSettings(team=OneToOneField(Team))` model on YOUR side rather than
  bloating this template.
- **Audit log.** The signal layer is already there — wire it to your
  event store.

## What this does NOT include

- The link to your domain models (see "Linking" above)
- Email transport (use the `notifications-multichannel` template + the
  `team_invite_sent` signal)
- Frontend code for the accept-invite page (the API + token are all you
  need; the page itself depends on your frontend stack)
- Ownership transfer (see "Extending")
