"""Django Admin registration for access-control models."""

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

from .models import AccessFunction, EmployeeProfile, Role, RoleFunctionPermission, UserFunctionOverride


class EmployeeProfileInline(admin.StackedInline):
    """Keep workspace role/profile management on the Django user page."""

    model = EmployeeProfile
    fk_name = "user"
    can_delete = False
    extra = 1
    max_num = 1
    autocomplete_fields = ["role", "organization_unit", "created_by"]


User = get_user_model()
admin.site.unregister(User)


@admin.register(User)
class RMWinsUserAdmin(UserAdmin):
    inlines = [EmployeeProfileInline]
    list_display = [*UserAdmin.list_display, "workspace_role", "account_type"]

    def get_inline_instances(self, request, obj=None):
        # The post-save signal creates the profile during user creation. Show the
        # inline on the subsequent change page to avoid creating it twice.
        if obj is None:
            return []
        return super().get_inline_instances(request, obj)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("employee_profile__role")

    @admin.display(description="Workspace role", ordering="employee_profile__role__name")
    def workspace_role(self, obj):
        profile = getattr(obj, "employee_profile", None)
        return getattr(getattr(profile, "role", None), "name", "-")

    @admin.display(description="Account type", ordering="employee_profile__account_type")
    def account_type(self, obj):
        profile = getattr(obj, "employee_profile", None)
        return profile.get_account_type_display() if profile else "-"


admin.site.site_header = "RMW Insights administration"
admin.site.site_title = "RMW Insights admin"
admin.site.index_title = "Workspace administration"


class RoleFunctionPermissionInline(admin.TabularInline):
    model = RoleFunctionPermission
    extra = 0


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "rank", "is_active", "is_system"]
    list_filter = ["is_active", "is_system"]
    search_fields = ["name", "slug", "description"]
    prepopulated_fields = {"slug": ["name"]}
    inlines = [RoleFunctionPermissionInline]


@admin.register(AccessFunction)
class AccessFunctionAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "module", "is_active"]
    list_filter = ["module", "is_active"]
    search_fields = ["code", "name", "description"]


@admin.register(EmployeeProfile)
class EmployeeProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "employee_id", "role", "organization_unit", "department", "job_title"]
    list_filter = ["role", "organization_unit__unit_type", "department"]
    search_fields = ["user__username", "user__first_name", "user__last_name", "employee_id"]


@admin.register(UserFunctionOverride)
class UserFunctionOverrideAdmin(admin.ModelAdmin):
    list_display = ["user", "function", "effect", "reason"]
    list_filter = ["effect", "function__module"]
    search_fields = ["user__username", "function__code", "reason"]
