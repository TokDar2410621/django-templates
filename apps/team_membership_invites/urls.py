"""Team membership URLs — mount on ``/api/teams/`` in your project.

    # config/urls.py
    urlpatterns = [
        path("api/teams/", include("team_membership_invites.urls")),
    ]
"""
from django.urls import path

from .views import (
    AcceptInviteView,
    DisbandView,
    InviteView,
    LeaveView,
    PendingInvitesView,
    RemoveMemberView,
    RevokeInviteView,
    TeamDetailView,
    TeamListCreateView,
    TeamMembersView,
)

app_name = "team_membership_invites"

urlpatterns = [
    # Collection
    path("", TeamListCreateView.as_view(), name="team-list-create"),

    # Invite flow (token-based; not nested under a team_id)
    path("accept/", AcceptInviteView.as_view(), name="team-accept"),
    path("invites/pending/", PendingInvitesView.as_view(), name="team-invites-pending"),
    path("invites/<str:token>/revoke/", RevokeInviteView.as_view(), name="team-invite-revoke"),

    # Team-scoped
    path("<int:team_id>/", TeamDetailView.as_view(), name="team-detail"),
    path("<int:team_id>/members/", TeamMembersView.as_view(), name="team-members"),
    path("<int:team_id>/invite/", InviteView.as_view(), name="team-invite"),
    path("<int:team_id>/leave/", LeaveView.as_view(), name="team-leave"),
    path("<int:team_id>/disband/", DisbandView.as_view(), name="team-disband"),
    path(
        "<int:team_id>/members/<int:user_id>/remove/",
        RemoveMemberView.as_view(),
        name="team-remove-member",
    ),
]
