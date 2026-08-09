import hashlib
import hmac
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import IntegrationCredentialState, Survey


INNOVATEMR_PROVIDER = "innovatemr"


@dataclass(frozen=True)
class CredentialReconciliation:
    configured: bool
    initialized: bool
    changed: bool
    links_cleared: int


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def reconcile_innovatemr_credential(token: str | None = None) -> CredentialReconciliation:
    """Clear stale InnovateMR links when the configured API token changes.

    Only a SHA-256 fingerprint is persisted. The first run establishes a safe
    baseline by clearing links whose credential provenance cannot be verified.
    """
    current_token = token if token is not None else settings.INNOVATEMR_API_TOKEN
    if not current_token:
        return CredentialReconciliation(False, False, False, 0)

    current_fingerprint = _fingerprint(current_token)
    with transaction.atomic():
        state = (
            IntegrationCredentialState.objects.select_for_update()
            .filter(provider=INNOVATEMR_PROVIDER)
            .first()
        )
        initialized = state is None
        if state and hmac.compare_digest(state.credential_fingerprint, current_fingerprint):
            return CredentialReconciliation(True, False, False, 0)

        innovate_surveys = Survey.objects.filter(
            Q(client__code=INNOVATEMR_PROVIDER) | Q(company_name__iexact="InnovateMR")
        )
        links_cleared = innovate_surveys.exclude(entry_link="", test_entry_link="").count()
        innovate_surveys.update(
            entry_link="",
            test_entry_link="",
            raw_data={},
            detail_synced_at=None,
            quota_synced_at=None,
            targeting_synced_at=None,
            updated_at=timezone.now(),
        )

        cleared_at = timezone.now()
        if state is None:
            IntegrationCredentialState.objects.create(
                provider=INNOVATEMR_PROVIDER,
                credential_fingerprint=current_fingerprint,
                last_cleared_at=cleared_at,
                last_cleared_links=links_cleared,
            )
        else:
            state.credential_fingerprint = current_fingerprint
            state.last_cleared_at = cleared_at
            state.last_cleared_links = links_cleared
            state.save(update_fields=[
                "credential_fingerprint", "last_cleared_at", "last_cleared_links", "updated_at"
            ])

    return CredentialReconciliation(True, initialized, not initialized, links_cleared)
