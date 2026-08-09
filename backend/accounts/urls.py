from django.urls import path

from .views import (
    WorkspaceLoginView,
    WorkspaceLogoutView,
    access_control_page,
    auth_login,
    auth_session,
    first_admin_setup,
)

urlpatterns = [
    path("login/", WorkspaceLoginView.as_view(), name="login"),
    path("logout/", WorkspaceLogoutView.as_view(), name="logout"),
    path("api/v1/auth/session/", auth_session, name="auth-session"),
    path("api/v1/auth/login/", auth_login, name="auth-login"),
    path("setup/", first_admin_setup, name="first-admin-setup"),
    path("access-control/", access_control_page, name="access-control"),
]
