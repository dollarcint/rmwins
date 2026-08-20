"""HTML authentication, Django-admin handoff and Access Control routes."""

from django.urls import path

from .views import (
    WorkspaceLoginView,
    WorkspaceLogoutView,
    access_control_page,
    auth_login,
    auth_session,
    cint_email_pool_import,
    first_admin_setup,
)

urlpatterns = [
    path("api/v1/auth/session/", auth_session, name="auth-session"),
    path("api/v1/auth/login/", auth_login, name="auth-login"),
    path("login/", WorkspaceLoginView.as_view(), name="login"),
    path("logout/", WorkspaceLogoutView.as_view(), name="logout"),
    path("setup/", first_admin_setup, name="first-admin-setup"),
    path("access-control/", access_control_page, name="access-control"),
    path(
        "access-control/cint-email-pool/import/",
        cint_email_pool_import,
        name="cint-email-pool-import",
    ),
]
