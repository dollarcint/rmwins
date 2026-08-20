"""Server-rendered inventory forms for surveys that do not have an API feed."""

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django import forms
from django.utils import timezone

from vendors.models import Client

from .models import Survey


RID_PARAMETER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")


def prepare_manual_entry_link(entry_link: str, rid_parameter: str) -> str:
    """Return a canonical template containing exactly one RM Wins RID slot."""

    parts = urlsplit((entry_link or "").strip())
    parameter = (rid_parameter or "").strip()
    kept = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.casefold() != parameter.casefold()
    ]
    kept.append((parameter, "[%%rid%%]"))
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment)
    )


class ManualSurveyForm(forms.ModelForm):
    rid_parameter = forms.CharField(
        label="Respondent ID parameter",
        max_length=64,
        initial="pid",
        help_text=(
            "The client parameter that should receive our unique RID, for example "
            "pid, rid or respondent_id."
        ),
    )

    class Meta:
        model = Survey
        fields = [
            "client",
            "source_key",
            "name",
            "entry_link",
            "cpi",
            "sample_size",
            "loi",
            "incidence_rate",
            "country",
            "country_code",
            "language",
            "language_code",
            "buyer_id",
            "survey_type",
            "device_type",
        ]
        labels = {
            "source_key": "Client survey ID",
            "entry_link": "Client entry link",
            "cpi": "Source CPI (USD)",
            "sample_size": "Target completes",
            "loi": "LOI (minutes)",
            "incidence_rate": "Incidence rate (%)",
            "buyer_id": "Buyer / sub-client ID",
            "survey_type": "Survey type",
        }
        help_texts = {
            "source_key": "The survey identifier supplied by this client.",
            "entry_link": "The original HTTPS link. Its RID parameter is added automatically.",
            "cpi": (
                "Store the full client CPI here. Supplier/client/project cuts are applied "
                "later by the existing allocation policy and frozen on each hit."
            ),
            "sample_size": "Used as the manual survey's target and initial available quantity.",
        }
        widgets = {
            "entry_link": forms.URLInput(attrs={"placeholder": "https://client.example/start?survey=123"}),
            "source_key": forms.TextInput(attrs={"placeholder": "Client survey ID"}),
            "name": forms.TextInput(attrs={"placeholder": "Survey name"}),
            "cpi": forms.NumberInput(attrs={"min": "0", "step": "0.01", "placeholder": "0.00"}),
            "sample_size": forms.NumberInput(attrs={"min": "1", "step": "1"}),
            "loi": forms.NumberInput(attrs={"min": "1", "step": "1"}),
            "incidence_rate": forms.NumberInput(attrs={"min": "0", "max": "100", "step": "0.01"}),
            "country_code": forms.TextInput(attrs={"placeholder": "US", "maxlength": "8"}),
            "language_code": forms.TextInput(attrs={"placeholder": "EN", "maxlength": "8"}),
            "buyer_id": forms.TextInput(attrs={"placeholder": "Optional"}),
            "device_type": forms.Select(
                choices=(("All", "All devices"), ("Desktop", "Desktop"), ("Mobile", "Mobile"), ("Tablet", "Tablet"))
            ),
            "survey_type": forms.Select(choices=(("B2C", "B2C"), ("B2B", "B2B"))),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].queryset = Client.objects.filter(is_active=True).order_by("name", "id")
        self.fields["client"].empty_label = "Select client"
        self.fields["name"].required = True
        self.fields["source_key"].required = True
        self.fields["cpi"].required = True
        self.fields["sample_size"].required = True
        self.fields["loi"].required = True
        self.fields["incidence_rate"].required = True
        self.fields["country_code"].required = True
        self.fields["language_code"].required = True
        self.fields["survey_type"].required = True
        self.fields["device_type"].required = True
        if not self.is_bound:
            self.initial["sample_size"] = None

    def clean_source_key(self):
        value = (self.cleaned_data.get("source_key") or "").strip()
        if not value:
            raise forms.ValidationError("Enter the client survey ID.")
        return value

    def clean_rid_parameter(self):
        value = (self.cleaned_data.get("rid_parameter") or "").strip()
        if not RID_PARAMETER_RE.fullmatch(value):
            raise forms.ValidationError(
                "Use 1-64 letters, numbers, dots, dashes or underscores; start with a letter."
            )
        return value

    def clean_entry_link(self):
        value = (self.cleaned_data.get("entry_link") or "").strip()
        parts = urlsplit(value)
        if parts.scheme.lower() != "https" or not parts.hostname:
            raise forms.ValidationError("Enter a complete HTTPS client link.")
        if parts.username or parts.password:
            raise forms.ValidationError("Credentials are not allowed inside the entry link.")
        return value

    def clean_incidence_rate(self):
        value = self.cleaned_data.get("incidence_rate")
        if value is not None and value > 100:
            raise forms.ValidationError("Incidence rate cannot exceed 100%.")
        return value

    def clean_sample_size(self):
        value = self.cleaned_data.get("sample_size")
        if value is not None and value < 1:
            raise forms.ValidationError("Target completes must be at least 1.")
        return value

    def clean_loi(self):
        value = self.cleaned_data.get("loi")
        if value is not None and value < 1:
            raise forms.ValidationError("LOI must be at least 1 minute.")
        return value

    def clean_country_code(self):
        return (self.cleaned_data.get("country_code") or "").strip().upper()

    def clean_language_code(self):
        return (self.cleaned_data.get("language_code") or "").strip().upper()

    def clean(self):
        cleaned = super().clean()
        client = cleaned.get("client")
        source_key = cleaned.get("source_key")
        if client and source_key and Survey.objects.filter(
            client=client,
            source_key=source_key,
            inventory_source=Survey.InventorySource.MANUAL,
        ).exists():
            self.add_error(
                "source_key",
                "A manual survey with this client survey ID already exists for the selected client.",
            )
        return cleaned

    def save(self, *, created_by, commit=True):
        survey = super().save(commit=False)
        survey.inventory_source = Survey.InventorySource.MANUAL
        survey.integration = None
        survey.source_id = None
        survey.manual_rid_parameter = self.cleaned_data["rid_parameter"]
        survey.entry_link = prepare_manual_entry_link(
            self.cleaned_data["entry_link"], survey.manual_rid_parameter
        )
        survey.company_name = survey.client.name
        survey.group_type = "Business" if survey.survey_type == "B2B" else "Consumer"
        survey.remaining = survey.sample_size
        survey.completes = 0
        survey.starts = 0
        survey.status = Survey.Status.LIVE
        survey.created_by = created_by
        survey.raw_data = {
            "manual_inventory": {
                "rid_parameter": survey.manual_rid_parameter,
                "original_entry_link": self.cleaned_data["entry_link"],
            }
        }
        now = timezone.now()
        survey.source_created_at = now
        survey.source_modified_at = now
        survey.detail_synced_at = now
        survey.quota_synced_at = now
        survey.targeting_synced_at = now
        if commit:
            survey.save()
        return survey
