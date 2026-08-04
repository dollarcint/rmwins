from django.contrib import admin

from .models import SurveySession


@admin.register(SurveySession)
class SurveySessionAdmin(admin.ModelAdmin):
    list_display = (
        "public_id",
        "client",
        "survey_id",
        "status",
        "transaction_id",
        "respondent_id",
        "created_at",
        "returned_at",
    )
    list_filter = ("client", "status", "created_at")
    search_fields = ("survey_id", "transaction_id", "respondent_id", "public_id")
    readonly_fields = (
        "public_id",
        "client",
        "survey_id",
        "transaction_id",
        "respondent_id",
        "entry_url",
        "status",
        "prescreener_answers",
        "supplier_status_id",
        "created_at",
        "handed_off_at",
        "returned_at",
    )
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False
