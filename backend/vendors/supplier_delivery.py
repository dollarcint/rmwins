"""External-supplier inventory links and respondent outcome redirects."""

import hashlib
import hmac
from urllib.parse import quote, urlencode

from django.urls import reverse

from surveys.outcomes import provider_outcome
from surveys.models import SurveyAttempt

from .credentials import decrypt_secret
from .models import VendorAPIKey, VendorCommercialProfile


def supplier_survey_identifier(profile: VendorCommercialProfile, survey) -> str:
    if profile.survey_id_mode == VendorCommercialProfile.SurveyIdMode.SOURCE_ID:
        return str(survey.source_identifier)
    return str(survey.local_id)


def supplier_entry_signature(api_key: VendorAPIKey, survey_local_id: str) -> str:
    payload = f"{api_key.public_id}:{survey_local_id}".encode("utf-8")
    return hmac.new(api_key.key_hash.encode("ascii"), payload, hashlib.sha256).hexdigest()


def verify_supplier_entry_signature(api_key, survey_local_id, received) -> bool:
    received = str(received or "").strip().lower()
    return len(received) == 64 and hmac.compare_digest(
        supplier_entry_signature(api_key, survey_local_id), received
    )


def supplier_entry_link(request, api_key: VendorAPIKey, survey) -> str:
    path = reverse("supplier-survey-start")
    base = request.build_absolute_uri(path)
    query = urlencode({
        "key": str(api_key.public_id),
        "survey": survey.local_id,
        "token": supplier_entry_signature(api_key, survey.local_id),
        "pid": "[%%pid%%]",
    }, safe="[]%")
    return f"{base}?{query}"


def _redirect_url_for_status(allocation, status_code, *, invalid=False):
    if invalid and allocation.invalid_redirect_url:
        return allocation.invalid_redirect_url
    return {
        SurveyAttempt.Status.COMPLETED: allocation.complete_redirect_url,
        SurveyAttempt.Status.TERMINATED: allocation.terminate_redirect_url,
        SurveyAttempt.Status.OVER_QUOTA: allocation.over_quota_redirect_url,
        SurveyAttempt.Status.QUALITY_TERMINATED: allocation.quality_redirect_url,
    }.get(status_code, "")


def supplier_outcome_signature(secret, *, pid, status, survey_id, term_reason):
    canonical = urlencode({
        "pid": pid,
        "status": status,
        "survey_id": survey_id,
        "term_reason": term_reason,
    })
    return hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def supplier_outcome_redirect(attempt) -> str:
    """Return the supplier redirect URL, forwarding the normalized client reason."""

    allocation = attempt.client_allocation
    if not attempt.vendor_id or not allocation or not attempt.supplier_respondent_id:
        return ""
    profile = getattr(attempt.vendor, "vendor_commercial_profile", None)
    if not profile or not profile.is_active:
        return ""
    invalid = attempt.status_source in {
        "innovatemr_hash_rejected", "innovatemr_status_rejected",
        "unsigned_callback_endpoint",
    }
    redirect_url = _redirect_url_for_status(allocation, attempt.status, invalid=invalid)
    if not redirect_url:
        return ""
    outcome = provider_outcome(attempt)
    term_reason = outcome.get("reason", "")
    if invalid and not term_reason:
        term_reason = "Invalid survey hit"
    survey_id = supplier_survey_identifier(profile, attempt.survey)
    parameters = {
        "pid": attempt.supplier_respondent_id,
        "status": attempt.status,
        "survey_id": survey_id,
        "term_reason": term_reason,
    }
    if profile.callback_hash_enabled:
        secret = decrypt_secret(profile.encrypted_callback_hash_secret)
        if not secret:
            return ""
        parameters["hash"] = supplier_outcome_signature(secret, **parameters)

    placeholder_values = {
        "[%%rid%%]": attempt.rid,
        "[%%pid%%]": parameters["pid"],
        "[%%status%%]": parameters["status"],
        "[%%survey_id%%]": parameters["survey_id"],
        "[%%surveyid%%]": parameters["survey_id"],
        "[%%term_reason%%]": parameters["term_reason"],
        "[%%termreason%%]": parameters["term_reason"],
        "[%%hash%%]": parameters.get("hash", ""),
    }
    for placeholder, value in placeholder_values.items():
        redirect_url = redirect_url.replace(
            placeholder,
            quote(str(value or ""), safe=""),
        )
    return redirect_url
