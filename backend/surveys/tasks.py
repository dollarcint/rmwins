"""Celery task boundary for scheduled provider work and attempt reconciliation."""

import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db.models import F, Q
from django.utils import timezone

from vendors.models import ClientIntegration
from vendors.credentials import resolve_integration_token

from .integrations import InnovateMRAPIError, InnovateMRClient
from .models import CintWebhookDelivery, Survey, SurveyAttempt, SyncLease
from .services import reconcile_attempt_status, replace_survey_details, sync_surveys
from .provider_services import (
    refresh_client_integration_details,
    sync_cint_redirect_contracts,
    sync_client_integration,
)
from .providers import has_provider


logger = logging.getLogger(__name__)


def _close_client(client) -> None:
    """Best-effort cleanup that must never strand a database lease."""

    close_client = getattr(client, "close", None)
    if close_client is None:
        return
    try:
        close_client()
    except Exception:
        logger.warning("Could not close an upstream HTTP client", exc_info=True)


def _stale_surveys(integration, limit):
    return Survey.objects.filter(integration=integration, status=Survey.Status.LIVE).filter(
        Q(quota_synced_at__isnull=True)
        | Q(targeting_synced_at__isnull=True)
        | Q(source_modified_at__isnull=False, quota_synced_at__lt=F("source_modified_at"))
        | Q(source_modified_at__isnull=False, targeting_synced_at__lt=F("source_modified_at"))
    ).order_by(
        F("detail_synced_at").asc(nulls_first=True),
        F("source_modified_at").desc(nulls_last=True),
    )[:limit]


def _claim_integration_dispatch(integration, claimed_at):
    """Atomically claim a snapshot so concurrent dispatchers cannot enqueue it twice."""

    queryset = ClientIntegration.objects.filter(
        pk=integration.pk,
        is_active=True,
        last_sync_status=integration.last_sync_status,
    )
    for field in ("last_sync_started_at", "last_sync_finished_at"):
        value = getattr(integration, field)
        if value is None:
            queryset = queryset.filter(**{f"{field}__isnull": True})
        else:
            queryset = queryset.filter(**{field: value})
    return queryset.update(
        last_sync_started_at=claimed_at,
        last_sync_status="queued",
        last_sync_error="",
        updated_at=claimed_at,
    ) == 1


@shared_task(name="surveys.dispatch_due_integrations", ignore_result=True)
def dispatch_due_integrations_task():
    now = timezone.now()
    queued = []
    integrations = list(
        ClientIntegration.objects.filter(is_active=True).filter(
            Q(client__is_active=True) | Q(provider_code__in=("biobrain", "voqall")),
        ).filter(
            Q(scheduled_sync_enabled=True)
            | Q(provider_code="innovatemr")
            | Q(provider_code="rfg", last_test_status="success")
            | Q(provider_code="cint", last_test_status="success")
        ).only(
            "id", "provider_code", "sync_interval_seconds", "last_sync_started_at",
            "last_sync_finished_at", "last_sync_status",
            "credential_env_key", "encrypted_api_token", "config",
        )
    )
    lease_names = {f"integration-{integration.pk}-sync" for integration in integrations}
    active_leases = set(
        SyncLease.objects.filter(
            name__in=lease_names,
            locked_until__gt=now,
        ).values_list("name", flat=True)
    )
    claim_timeout = timedelta(
        seconds=settings.CLIENT_INTEGRATION_DISPATCH_CLAIM_TIMEOUT_SECONDS
    )
    for integration in integrations:
        if (
            integration.provider_code == "cint"
            and (integration.config or {}).get("opportunities_webhook_enabled") is True
        ):
            continue
        if integration.provider_code in {"biobrain", "voqall"} and not resolve_integration_token(integration):
            continue
        lease_name = f"integration-{integration.pk}-sync"
        if lease_name in active_leases:
            continue
        claim_is_active = (
            integration.last_sync_status in {"queued", "running"}
            and integration.last_sync_started_at
            and integration.last_sync_started_at > now - claim_timeout
        )
        if claim_is_active:
            continue
        claim_is_stale = bool(
            integration.last_sync_status in {"queued", "running"}
            and integration.last_sync_started_at
            and integration.last_sync_started_at <= now - claim_timeout
        )
        interval_seconds = {
            "innovatemr": settings.CLIENT_INTEGRATION_INNOVATEMR_SYNC_INTERVAL_SECONDS,
            "rfg": settings.CLIENT_INTEGRATION_RFG_SYNC_INTERVAL_SECONDS,
            "cint": settings.CLIENT_INTEGRATION_CINT_SYNC_INTERVAL_SECONDS,
        }.get(integration.provider_code, integration.sync_interval_seconds)
        minimum_interval_seconds = 30 if integration.provider_code == "enligne" else 60
        interval_seconds = max(minimum_interval_seconds, interval_seconds)
        if integration.provider_code == "enligne":
            # Enligne's 30-second interval is start-to-start. The integration
            # lease still prevents overlap if a fetch takes longer than usual.
            last_activity = integration.last_sync_started_at or integration.last_sync_finished_at
        else:
            last_activity = max(
                filter(
                    None,
                    (
                        integration.last_sync_started_at,
                        integration.last_sync_finished_at,
                    ),
                ),
                default=None,
            )
        due_at = (last_activity or (now - timedelta(days=1))) + timedelta(
            seconds=interval_seconds
        )
        # The worker records its real start a few milliseconds after the
        # dispatcher tick. Without this tolerance, a 30-second Enligne job can
        # miss the next tick and accidentally run once per minute.
        due_tolerance = timedelta(seconds=1) if integration.provider_code == "enligne" else timedelta()
        if (
            (claim_is_stale or due_at <= now + due_tolerance)
            and _claim_integration_dispatch(integration, now)
        ):
            try:
                sync_client_integration_task.delay(
                    integration.pk, dispatch_claim=True
                )
            except Exception as exc:
                # Publishing can fail after the atomic DB claim. Revert only
                # if no worker has already consumed that exact timestamped
                # claim, so a broker outage does not suppress retries until
                # the normal queued-claim timeout.
                ClientIntegration.objects.filter(
                    pk=integration.pk,
                    last_sync_status="queued",
                    last_sync_started_at=now,
                ).update(
                    last_sync_started_at=integration.last_sync_started_at,
                    last_sync_status="failed",
                    last_sync_error=(
                        f"Could not queue integration sync: {exc}"
                    )[:10000],
                    updated_at=timezone.now(),
                )
                raise
            queued.append(integration.pk)
    return {"queued": queued, "count": len(queued)}


@shared_task(
    name="surveys.sync_client_integration",
    soft_time_limit=240,
    time_limit=270,
)
def sync_client_integration_task(integration_id, dispatch_claim=False):
    integration = ClientIntegration.objects.select_related("client").get(pk=integration_id, is_active=True)
    lease_name = f"integration-{integration_id}-sync"
    if not SyncLease.acquire(lease_name, seconds=max(300, integration.sync_interval_seconds)):
        return {"status": "skipped", "reason": "previous integration sync is still running"}
    started_at = timezone.now()
    if dispatch_claim:
        transitioned = ClientIntegration.objects.filter(
            pk=integration_id,
            is_active=True,
            last_sync_status="queued",
        ).update(
            last_sync_started_at=started_at,
            last_sync_status="running",
            last_sync_error="",
            updated_at=started_at,
        )
        if not transitioned:
            SyncLease.release(lease_name)
            return {"status": "skipped", "reason": "dispatch claim is no longer current"}
        integration.last_sync_started_at = started_at
        integration.last_sync_status = "running"
        integration.last_sync_error = ""
    else:
        integration.last_sync_started_at = started_at
        integration.last_sync_status = "running"
        integration.last_sync_error = ""
        integration.save(update_fields=["last_sync_started_at", "last_sync_status", "last_sync_error", "updated_at"])
    api = None
    try:
        if has_provider(integration.provider_code):
            run = sync_client_integration(integration, refresh_details=False)
            details = refresh_client_integration_details(integration)
            summary = {
                "run_id": run.pk,
                "status": run.status,
                "created": run.created,
                "updated": run.updated,
                "unchanged": run.unchanged,
                "closed": run.closed,
                "details_refreshed": details["refreshed"],
                "detail_failures": details["failures"],
            }
            integration.last_sync_status = (
                "success" if run.status == "success" and not details["failures"] else "partial"
            )
            integration.last_sync_summary = summary
            if integration.provider_code == "cint":
                sync_cint_redirects_task.delay(integration.pk)
                summary["redirect_updates_queued"] = True
            return summary
        api = InnovateMRClient(integration=integration)
        summary = sync_surveys(api, integration=integration).__dict__
        inventory_count = sum(int(summary.get(key) or 0) for key in ("created", "updated", "unchanged"))
        if integration.provider_code in {"biobrain", "voqall"} and inventory_count > 0 and not integration.client.is_active:
            integration.client.is_active = True
            integration.client.save(update_fields=["is_active", "updated_at"])
        refreshed = failures = 0
        for survey in _stale_surveys(integration, integration.detail_refresh_batch):
            try:
                replace_survey_details(api, survey)
                refreshed += 1
            except Exception:
                failures += 1
        summary.update({"details_refreshed": refreshed, "detail_failures": failures})
        integration.last_sync_status = "success" if not failures else "partial"
        integration.last_sync_summary = summary
        return summary
    except Exception as exc:
        integration.last_sync_status = "failed"
        integration.last_sync_error = str(exc)[:10000]
        raise
    finally:
        _close_client(api)
        try:
            integration.last_sync_finished_at = timezone.now()
            integration.save(update_fields=[
                "last_sync_finished_at", "last_sync_status", "last_sync_error", "last_sync_summary", "updated_at",
            ])
        finally:
            SyncLease.release(lease_name)


@shared_task(
    name="surveys.sync_cint_redirects",
    soft_time_limit=240,
    time_limit=270,
)
def sync_cint_redirects_task(integration_id, batch_size=25, force=False, after_id=0):
    """Configure new/backfill Cint survey callbacks in serialized batches."""

    lease_name = f"cint-redirects-{integration_id}"
    if not SyncLease.acquire(lease_name, seconds=300):
        return {"status": "skipped", "reason": "redirect batch already running"}
    continue_batching = False
    result = {"next_after_id": max(0, int(after_id or 0))}
    try:
        integration = ClientIntegration.objects.select_related("client").get(
            pk=integration_id,
            is_active=True,
            provider_code="cint",
        )
        result = sync_cint_redirect_contracts(
            integration,
            batch_size=batch_size,
            force=force,
            after_id=after_id,
        )
        continue_batching = result["remaining"] > 0
        result["status"] = "success" if not result["failures"] else "partial"
        return result
    finally:
        SyncLease.release(lease_name)
        if continue_batching:
            sync_cint_redirects_task.apply_async(
                args=[integration_id],
                kwargs={
                    "batch_size": batch_size,
                    "force": force,
                    "after_id": result.get("next_after_id", 0),
                },
                countdown=1,
            )


@shared_task(
    name="surveys.process_cint_opportunities_delivery",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
    soft_time_limit=600,
    time_limit=630,
)
def process_cint_opportunities_delivery_task(delivery_id):
    """Process a verified Cint webhook receipt outside the public request."""

    from .cint_webhooks import process_delivery

    delivery_ref = CintWebhookDelivery.objects.only("integration_id").get(pk=delivery_id)
    lease_name = f"cint-webhook-{delivery_ref.integration_id}"
    if not SyncLease.acquire(lease_name, seconds=700):
        raise RuntimeError("A previous Cint webhook delivery is still processing.")
    try:
        delivery = process_delivery(delivery_id)
    except Exception as exc:
        CintWebhookDelivery.objects.filter(pk=delivery_id).update(
            status=CintWebhookDelivery.Status.FAILED,
            error=str(exc)[:10000],
        )
        raise
    finally:
        SyncLease.release(lease_name)
    return {
        "delivery_id": delivery.pk,
        "status": delivery.status,
        "created": delivery.created_count,
        "updated": delivery.updated_count,
        "closed": delivery.closed_count,
        "skipped": delivery.skipped_count,
        "errors": delivery.error_count,
    }


@shared_task(name="surveys.sync_innovatemr_surveys")
def sync_innovatemr_surveys_task():
    integration = ClientIntegration.objects.filter(
        is_active=True, client__is_active=True, provider_code="innovatemr"
    ).order_by("id").first()
    if not integration:
        return {"status": "skipped", "reason": "no active integration"}
    return sync_client_integration_task(integration.pk)


@shared_task(name="surveys.refresh_stale_details")
def refresh_stale_details_task():
    integration = ClientIntegration.objects.filter(
        is_active=True,
        client__is_active=True,
        provider_code__in=("innovatemr", "biobrain", "voqall"),
    ).order_by("id").first()
    if not integration:
        return {"status": "skipped", "reason": "no active integration"}
    api = InnovateMRClient(integration=integration)
    refreshed = failures = 0
    try:
        for survey in _stale_surveys(integration, integration.detail_refresh_batch):
            try:
                replace_survey_details(api, survey)
                refreshed += 1
            except Exception:
                failures += 1
    finally:
        _close_client(api)
    return {"refreshed": refreshed, "failures": failures}


@shared_task(name="surveys.reconcile_pending_attempts", ignore_result=True)
def reconcile_pending_attempts_task():
    lease_name = "innovatemr-attempt-reconciliation"
    if not SyncLease.acquire(lease_name, seconds=300):
        return {"status": "skipped", "reason": "previous attempt reconciliation is still running"}
    now = timezone.now()
    retry_before = now - timedelta(seconds=settings.INNOVATEMR_ATTEMPT_RECONCILE_INTERVAL_SECONDS)
    lookback = now - timedelta(hours=settings.INNOVATEMR_ATTEMPT_RECONCILE_LOOKBACK_HOURS)
    pending = SurveyAttempt.objects.select_related("survey__integration").filter(
        status=SurveyAttempt.Status.REDIRECTED, callback_at__isnull=True, initiated_at__gte=lookback,
    ).exclude(survey__integration__provider_code__in=("rfg", "cint", "enligne")).filter(
        Q(upstream_checked_at__isnull=True) | Q(upstream_checked_at__lte=retry_before)
    ).order_by(
        F("upstream_checked_at").asc(nulls_first=True),
        F("initiated_at").desc(),
    )[: settings.INNOVATEMR_ATTEMPT_RECONCILE_BATCH]
    clients = {}
    checked = terminal = failures = 0
    try:
        for attempt in pending:
            try:
                integration = attempt.survey.integration
                integration_id = integration.pk if integration else None
                client = clients.get(integration_id)
                if client is None:
                    client = InnovateMRClient(integration=integration)
                    clients[integration_id] = client
                terminal += int(reconcile_attempt_status(client, attempt))
                checked += 1
            except InnovateMRAPIError:
                SurveyAttempt.objects.filter(pk=attempt.pk).update(upstream_checked_at=now)
                failures += 1
        return {"checked": checked, "terminal": terminal, "failures": failures}
    finally:
        for client in clients.values():
            _close_client(client)
        SyncLease.release(lease_name)
