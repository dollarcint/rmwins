"""Validated workspace login form."""

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from .models import EmployeeProfile


class WorkspaceAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={"autofocus": True, "placeholder": "Username"}),
    )
    password = forms.CharField(
        max_length=1024,
        strip=False,
        widget=forms.PasswordInput(attrs={"placeholder": "Password"}),
    )
    remember_me = forms.BooleanField(required=False, initial=True)

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        profile = getattr(user, "employee_profile", None)
        if getattr(profile, "account_type", "") != EmployeeProfile.AccountType.EXTERNAL_VENDOR:
            return
        commercial = getattr(user, "vendor_commercial_profile", None)
        if not commercial or not commercial.is_active or not commercial.panel_access_enabled:
            raise ValidationError(
                "Panel access is not enabled for this supplier account.",
                code="panel_access_disabled",
            )

