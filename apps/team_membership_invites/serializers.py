"""Serializers for team_membership_invites.

The serializers are intentionally read-mostly. Writes go through
``services.*`` from the view layer, not through ``serializer.save()`` —
that's where transactions, signals, and permission checks live.
"""
from __future__ import annotations

from rest_framework import serializers

from .models import Team, TeamInvite, TeamMember


class TeamMemberSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source="user.pk", read_only=True)
    email = serializers.CharField(source="user.email", read_only=True)
    display_name = serializers.SerializerMethodField()
    is_creator = serializers.SerializerMethodField()

    class Meta:
        model = TeamMember
        fields = (
            "user_id",
            "email",
            "display_name",
            "role",
            "is_creator",
            "joined_at",
        )
        read_only_fields = fields

    def get_display_name(self, obj: TeamMember) -> str:
        # Support common conventions; fall back to email local-part.
        for attr in ("display_name", "name", "username", "get_full_name"):
            if hasattr(obj.user, attr):
                val = getattr(obj.user, attr)
                if callable(val):
                    val = val()
                if val:
                    return str(val)
        return (obj.user.email or "").split("@", 1)[0]

    def get_is_creator(self, obj: TeamMember) -> bool:
        return obj.team.creator_id == obj.user_id


class TeamInviteSerializer(serializers.ModelSerializer):
    is_pending = serializers.BooleanField(read_only=True)

    class Meta:
        model = TeamInvite
        fields = (
            "token",
            "email",
            "expires_at",
            "accepted_at",
            "revoked_at",
            "created_at",
            "is_pending",
        )
        read_only_fields = fields


class TeamSerializer(serializers.ModelSerializer):
    """Full team payload — id, name, members, invites (creator only).

    Pending invites are only included if the requesting user is the
    creator. Pass ``context={"request": request}`` from the view.
    """

    members = serializers.SerializerMethodField()
    invites = serializers.SerializerMethodField()
    creator_id = serializers.IntegerField(source="creator.pk", read_only=True)

    class Meta:
        model = Team
        fields = (
            "id",
            "slug",
            "name",
            "creator_id",
            "created_at",
            "members",
            "invites",
        )
        read_only_fields = fields

    def get_members(self, team: Team):
        from .selectors import list_team_members

        return TeamMemberSerializer(list_team_members(team), many=True).data

    def get_invites(self, team: Team):
        request = self.context.get("request") if self.context else None
        viewer = getattr(request, "user", None)
        if viewer is None or not viewer.is_authenticated or viewer.id != team.creator_id:
            return []
        from .selectors import pending_invites_for_team

        return TeamInviteSerializer(pending_invites_for_team(team), many=True).data


class InviteRequestSerializer(serializers.Serializer):
    """Body schema for POST /teams/<id>/invite/ — just an email."""

    email = serializers.EmailField()


class CreateTeamRequestSerializer(serializers.Serializer):
    """Body schema for POST /teams/ — name (required) + slug (optional)."""

    name = serializers.CharField(max_length=80)
    slug = serializers.SlugField(max_length=80, required=False, allow_blank=True)


class AcceptInviteRequestSerializer(serializers.Serializer):
    """Body schema for POST /teams/accept/."""

    token = serializers.CharField(max_length=64)
