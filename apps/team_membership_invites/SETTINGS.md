# SETTINGS — team-membership-invites

## pip dependencies

```
djangorestframework>=3.14
```

Optional:

```
django-unfold        # if your admin uses Unfold; otherwise falls back to stock ModelAdmin
```

## INSTALLED_APPS

```python
INSTALLED_APPS = [
    # ...
    "rest_framework",
    "team_membership_invites",
]
```

## URLs

```python
# config/urls.py
from django.urls import path, include

urlpatterns = [
    # ...
    path("api/teams/", include("team_membership_invites.urls")),
]
```

## Configurable settings (all optional)

```python
# settings.py — all four have sensible defaults; override as needed

# Invitation token lifetime. After this many days, accept_invite() rejects
# the token with "Invitation has expired."
TEAM_INVITE_EXPIRY_DAYS = 14

# Permission to invite. By default only the creator can invite; flip this
# to True if any member should be able to send invitations.
TEAM_ALLOW_MEMBER_INVITES = False

# Role choices stored in TeamMember.role. The string "creator" is the
# PERMISSION ANCHOR — don't rename it. You can add additional roles
# (e.g. "admin", "viewer") and use them in YOUR domain-side permission
# logic, but the template itself only cares about creator vs. non-creator.
TEAM_ROLE_CHOICES = [
    ("creator", "Creator"),
    ("admin",   "Admin"),
    ("member",  "Member"),
    ("viewer",  "Viewer"),
]

# Frontend URL pattern for the accept-invite link. Used by YOUR signal
# receiver (in your notifications layer) to build the URL that's emailed
# to the invitee. The {token} placeholder is required.
TEAM_INVITE_URL_TEMPLATE = "https://app.example.com/teams/accept?token={token}"
```

## Env vars

None required by the template itself. Your notification layer's email
transport will have its own env vars (API keys, etc.).

## Post-install verification

```bash
python manage.py check
python manage.py migrate
python manage.py test team_membership_invites
# or with pytest:
pytest apps/team_membership_invites/tests/

# curl smoke (assuming JWT auth):
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"email":"creator@example.com","password":"pwpwpwpw"}' \
  | python -c "import sys, json; print(json.load(sys.stdin)['access'])")

# Create a team
curl -s -X POST http://127.0.0.1:8000/api/teams/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Acme"}'

# Invite someone
curl -s -X POST http://127.0.0.1:8000/api/teams/1/invite/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"email":"newhire@example.com"}'
```
