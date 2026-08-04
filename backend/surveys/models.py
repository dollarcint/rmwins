import uuid

from django.db import models


class SurveySession(models.Model):
    class Status(models.TextChoices):
        INITIATED = "initiated", "Initiated"
        HANDED_OFF = "handed_off", "Sent to survey"
        COMPLETE = "complete", "Complete"
        TERMINATE = "terminate", "Terminate"
        QUOTA_FULL = "quota_full", "Quota full"
        SECURITY_TERMINATE = "security_terminate", "Security terminate"

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    client = models.CharField(max_length=80, db_index=True)
    survey_id = models.CharField(max_length=160, db_index=True)
    transaction_id = models.CharField(max_length=64, unique=True)
    respondent_id = models.CharField(max_length=64, unique=True)
    entry_url = models.URLField(max_length=2000)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.INITIATED, db_index=True)
    prescreener_answers = models.JSONField(default=dict, blank=True)
    supplier_status_id = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    handed_off_at = models.DateTimeField(null=True, blank=True)
    returned_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("client", "survey_id", "-created_at"))]

    def __str__(self):
        return f"{self.client} {self.survey_id} - {self.get_status_display()}"
