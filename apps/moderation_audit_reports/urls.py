"""Moderation URLs — mount on ``/api/moderation/`` in your project."""
from django.urls import path

from .views import (
    AdminBanUserView,
    AdminReportDetailView,
    AdminReportListView,
    AdminTriageView,
    AdminUnbanUserView,
    ReportSubmitView,
)


app_name = "moderation_audit_reports"

urlpatterns = [
    # Public submit
    path("reports/", ReportSubmitView.as_view(), name="report-submit"),

    # Admin queue
    path("admin/reports/", AdminReportListView.as_view(), name="admin-report-list"),
    path(
        "admin/reports/<int:report_id>/",
        AdminReportDetailView.as_view(),
        name="admin-report-detail",
    ),
    path(
        "admin/reports/<int:report_id>/triage/",
        AdminTriageView.as_view(),
        name="admin-report-triage",
    ),

    # Admin ban / unban
    path(
        "admin/users/<int:user_id>/ban/",
        AdminBanUserView.as_view(),
        name="admin-user-ban",
    ),
    path(
        "admin/users/<int:user_id>/unban/",
        AdminUnbanUserView.as_view(),
        name="admin-user-unban",
    ),
]
