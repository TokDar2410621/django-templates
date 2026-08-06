"""URL wiring for auth_jwt_oauth.

Two namespaces, since /api/auth/ and /api/user/ are conventionally
mounted separately::

    # config/urls.py
    from auth_jwt_oauth.urls import auth_urls, user_urls

    urlpatterns = [
        # ...
        path("api/auth/", include((auth_urls, "smn_auth"), namespace="smn_auth")),
        path("api/user/", include((user_urls, "smn_user"), namespace="smn_user")),
    ]

Or, if you'd rather wire everything under one prefix::

    path("api/", include("auth_jwt_oauth.urls")),

which exposes both groups (auth/<...> + user/<...>) under that prefix.
"""
from __future__ import annotations

from django.urls import include, path
from rest_framework_simplejwt.views import TokenRefreshView

from .social_views import AppleLoginView, GoogleLoginView
from .views import (
    DeleteAccountView,
    EmailCheckView,
    LoginView,
    LogoutView,
    MeView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    SignupView,
    UpdateProfileView,
)

# /api/auth/<...>
auth_urls = [
    path("signup/", SignupView.as_view(), name="signup"),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("me/", MeView.as_view(), name="me"),
    path("check-email/", EmailCheckView.as_view(), name="check-email"),
    path("account/", DeleteAccountView.as_view(), name="delete-account"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path(
        "password-reset/request/",
        PasswordResetRequestView.as_view(),
        name="password-reset-request",
    ),
    path(
        "password-reset/confirm/",
        PasswordResetConfirmView.as_view(),
        name="password-reset-confirm",
    ),
    path("google/", GoogleLoginView.as_view(), name="google"),
    path("apple/", AppleLoginView.as_view(), name="apple"),
]

# /api/user/<...>
user_urls = [
    path("profile/", UpdateProfileView.as_view(), name="profile"),
]

app_name = "auth_jwt_oauth"

# Combined fallback wiring when the project mounts on a single prefix.
urlpatterns = [
    path("auth/", include((auth_urls, "smn_auth"))),
    path("user/", include((user_urls, "smn_user"))),
]
