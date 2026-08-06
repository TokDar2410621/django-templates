"""Admin for teams, members and invites.

This module tries to use ``unfold.admin.ModelAdmin`` if django-unfold is
installed; otherwise it falls back to the stock ``admin.ModelAdmin``.
"""
from __future__ import annotations

from django.contrib import admin, messages

try:
    from unfold.admin import ModelAdmin as BaseModelAdmin
    from unfold.admin import TabularInline as BaseTabularInline
except ImportError:  # pragma: no cover - optional dependency
    BaseModelAdmin = admin.ModelAdmin  # type: ignore[misc,assignment]
    BaseTabularInline = admin.TabularInline  # type: ignore[misc,assignment]

from .models import Team, TeamInvite, TeamMember
from .services import TeamServiceError, disband


class TeamMemberInline(BaseTabularInline):
    model = TeamMember
    extra = 0
    fields = ("user", "role", "joined_at")
    readonly_fields = ("joined_at",)
    autocomplete_fields = ("user",)


@admin.action(description="Disband selected teams")
def disband_selected(modeladmin, request, queryset):
    n = 0
    failed = 0
    for team in queryset:
        try:
            disband(team=team, by=request.user)
            n += 1
        except TeamServiceError as exc:
            failed += 1
            messages.warning(request, f"{team.name}: {exc}")
    if n:
        messages.success(request, f"{n} team(s) disbanded.")
    if failed:
        messages.error(request, f"{failed} team(s) could not be disbanded.")


@admin.register(Team)
class TeamAdmin(BaseModelAdmin):
    list_display = ("name", "slug", "creator", "member_count", "created_at")
    search_fields = ("name", "slug", "creator__email")
    readonly_fields = ("created_at",)
    autocomplete_fields = ("creator",)
    inlines = (TeamMemberInline,)
    actions = (disband_selected,)
    ordering = ("-created_at",)

    @admin.display(description="Members")
    def member_count(self, obj: Team) -> int:
        return obj.members.count()


@admin.register(TeamMember)
class TeamMemberAdmin(BaseModelAdmin):
    list_display = ("team", "user", "role", "joined_at")
    list_filter = ("role",)
    search_fields = ("team__name", "user__email")
    autocomplete_fields = ("team", "user")
    readonly_fields = ("joined_at",)


@admin.register(TeamInvite)
class TeamInviteAdmin(BaseModelAdmin):
    list_display = (
        "team", "email", "invited_by", "is_pending",
        "expires_at", "accepted_at", "revoked_at", "created_at",
    )
    list_filter = ("accepted_at", "revoked_at")
    search_fields = ("team__name", "email")
    autocomplete_fields = ("team", "invited_by")
    readonly_fields = (
        "token", "created_at", "accepted_at", "revoked_at",
    )

    @admin.display(boolean=True, description="Pending?")
    def is_pending(self, obj: TeamInvite) -> bool:
        return obj.is_pending
