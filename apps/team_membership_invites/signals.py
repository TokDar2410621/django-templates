"""Signals emitted by team_membership_invites.

These are the integration points for your project. Connect a receiver in
your own ``signals.py`` (or directly in ``apps.py::ready()``) to:

- Send the invitation email when ``team_invite_sent`` fires
- Notify other members when a new user joins (``team_member_added``)
- Update a denormalized counter when a member leaves (``team_member_removed``)

The template stays decoupled from any email transport / push provider;
hooking into these signals from your notification layer is the recommended
pattern. See README.md for an example wiring.
"""
from __future__ import annotations

import django.dispatch

# Fired AFTER a TeamInvite row is created (and committed to the DB).
# Receivers should send the invitation email here.
# kwargs: sender (the TeamInvite class), instance (the row), team, email, token, invited_by
team_invite_sent = django.dispatch.Signal()

# Fired AFTER accept_invite() inserts the TeamMember row.
# kwargs: sender (TeamMember class), instance, team, user
team_member_added = django.dispatch.Signal()

# Fired AFTER a member is removed (whether they left or were removed by the creator).
# kwargs: sender (TeamMember class), team, user, removed_by, was_self_leave (bool)
team_member_removed = django.dispatch.Signal()
