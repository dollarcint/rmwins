"""Focused regression tests for scheduled-task resource usage."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from django.utils import timezone

from vendors.models import Client, ClientIntegration

from .models import Survey, SurveyAttempt
from .tasks import (
    _claim_integration_dispatch,
    dispatch_due_integrations_task,
    refresh_stale_details_task,
    reconcile_pending_attempts_task,
    sync_client_integration_task,
)


class ScheduledTaskEfficiencyTests(TestCase):
    def _integration(self, suffix: str) -> ClientIntegration:
        client = Client.objects.create(
            code=f"task-client-{suffix}",
            name=f"Task Client {suffix}",
            provider_code="innovatemr",
        )
        return ClientIntegration.objects.create(
            client=client,
            name=f"Task Integration {suffix}",
            provider_code="innovatemr",
            base_url="https://supplier.innovatemr.net/api/v2",
            last_sync_started_at=timezone.now() - timedelta(days=1),
        )

    @override_settings(CLIENT_INTEGRATION_INNOVATEMR_SYNC_INTERVAL_SECONDS=60)
    @patch("surveys.tasks.sync_client_integration_task.delay")
    def test_dispatcher_lease_check_is_one_query_for_the_whole_batch(self, delay):
        ClientIntegration.objects.all().delete()
        integrations = [self._integration(str(index)) for index in range(3)]

        with self.assertNumQueries(5):
            result = dispatch_due_integrations_task.run()

        self.assertEqual(result["count"], 3)
        self.assertEqual(
            {call.args[0] for call in delay.call_args_list},
            {integration.pk for integration in integrations},
        )
        self.assertTrue(
            all(call.kwargs == {"dispatch_claim": True} for call in delay.call_args_list)
        )

    def test_dispatch_claim_is_atomic_for_two_stale_snapshots(self):
        integration = self._integration("atomic-claim")
        first_snapshot = ClientIntegration.objects.get(pk=integration.pk)
        second_snapshot = ClientIntegration.objects.get(pk=integration.pk)
        claimed_at = timezone.now()

        self.assertTrue(
            _claim_integration_dispatch(first_snapshot, claimed_at)
        )
        self.assertFalse(
            _claim_integration_dispatch(second_snapshot, claimed_at)
        )

    @override_settings(
        CLIENT_INTEGRATION_INNOVATEMR_SYNC_INTERVAL_SECONDS=60,
        CLIENT_INTEGRATION_DISPATCH_CLAIM_TIMEOUT_SECONDS=900,
    )
    @patch("surveys.tasks.sync_client_integration_task.delay")
    def test_dispatcher_does_not_duplicate_a_backlogged_queued_claim(self, delay):
        ClientIntegration.objects.all().delete()
        integration = self._integration("backlogged-claim")
        ClientIntegration.objects.filter(pk=integration.pk).update(
            last_sync_started_at=timezone.now() - timedelta(minutes=5),
            last_sync_finished_at=timezone.now() - timedelta(days=1),
            last_sync_status="queued",
        )

        result = dispatch_due_integrations_task.run()

        self.assertEqual(result, {"queued": [], "count": 0})
        delay.assert_not_called()

    @override_settings(
        CLIENT_INTEGRATION_INNOVATEMR_SYNC_INTERVAL_SECONDS=3600,
        CLIENT_INTEGRATION_DISPATCH_CLAIM_TIMEOUT_SECONDS=300,
    )
    @patch("surveys.tasks.sync_client_integration_task.delay")
    def test_dispatcher_recovers_a_lost_claim_after_timeout(self, delay):
        ClientIntegration.objects.all().delete()
        integration = self._integration("expired-claim")
        ClientIntegration.objects.filter(pk=integration.pk).update(
            last_sync_started_at=timezone.now() - timedelta(minutes=10),
            last_sync_status="queued",
        )

        result = dispatch_due_integrations_task.run()

        self.assertEqual(result["queued"], [integration.pk])
        delay.assert_called_once_with(integration.pk, dispatch_claim=True)

    @override_settings(
        CLIENT_INTEGRATION_INNOVATEMR_SYNC_INTERVAL_SECONDS=60,
        CLIENT_INTEGRATION_DISPATCH_CLAIM_TIMEOUT_SECONDS=900,
    )
    def test_broker_failure_releases_dispatch_claim_for_immediate_retry(self):
        ClientIntegration.objects.all().delete()
        integration = self._integration("broker-failure")
        previous_started_at = integration.last_sync_started_at

        with patch(
            "surveys.tasks.sync_client_integration_task.delay",
            side_effect=ConnectionError("broker unavailable"),
        ):
            with self.assertRaisesMessage(ConnectionError, "broker unavailable"):
                dispatch_due_integrations_task.run()

        integration.refresh_from_db()
        self.assertEqual(integration.last_sync_status, "failed")
        self.assertEqual(integration.last_sync_started_at, previous_started_at)
        self.assertIn("broker unavailable", integration.last_sync_error)

        with patch(
            "surveys.tasks.sync_client_integration_task.delay"
        ) as retry:
            result = dispatch_due_integrations_task.run()

        self.assertEqual(result["queued"], [integration.pk])
        retry.assert_called_once_with(integration.pk, dispatch_claim=True)

    @patch("surveys.tasks.SyncLease.release")
    @patch("surveys.tasks.SyncLease.acquire", return_value=True)
    def test_worker_rejects_a_stale_duplicate_dispatch_message(
        self, _acquire, release
    ):
        integration = self._integration("stale-message")
        integration.last_sync_status = "success"
        integration.save(update_fields=["last_sync_status", "updated_at"])

        result = sync_client_integration_task.run(
            integration.pk, dispatch_claim=True
        )

        self.assertEqual(
            result,
            {"status": "skipped", "reason": "dispatch claim is no longer current"},
        )
        release.assert_called_once_with(f"integration-{integration.pk}-sync")

    @override_settings(
        INNOVATEMR_ATTEMPT_RECONCILE_INTERVAL_SECONDS=60,
        INNOVATEMR_ATTEMPT_RECONCILE_LOOKBACK_HOURS=24,
        INNOVATEMR_ATTEMPT_RECONCILE_BATCH=20,
    )
    @patch("surveys.tasks.SyncLease.release")
    @patch("surveys.tasks.SyncLease.acquire", return_value=True)
    @patch("surveys.tasks.reconcile_attempt_status", return_value=False)
    @patch("surveys.tasks.InnovateMRClient")
    def test_reconciliation_reuses_and_closes_one_client_per_integration(
        self,
        client_class,
        reconcile,
        _acquire,
        _release,
    ):
        integration = self._integration("reconcile")
        survey = Survey.objects.create(
            client=integration.client,
            integration=integration,
            source_id=101,
            status=Survey.Status.LIVE,
        )
        for index in range(3):
            SurveyAttempt.objects.create(
                rid=f"Rc{index}Ab1Cd2E",
                survey=survey,
                user_id=f"respondent-{index}",
                status=SurveyAttempt.Status.REDIRECTED,
            )
        upstream_client = Mock()
        upstream_client.session = Mock()
        client_class.return_value = upstream_client

        result = reconcile_pending_attempts_task.run()

        self.assertEqual(result, {"checked": 3, "terminal": 0, "failures": 0})
        client_class.assert_called_once_with(integration=integration)
        self.assertEqual(reconcile.call_count, 3)
        upstream_client.close.assert_called_once_with()

    @override_settings(
        INNOVATEMR_ATTEMPT_RECONCILE_INTERVAL_SECONDS=60,
        INNOVATEMR_ATTEMPT_RECONCILE_LOOKBACK_HOURS=24,
        INNOVATEMR_ATTEMPT_RECONCILE_BATCH=20,
    )
    @patch("surveys.tasks.SyncLease.release")
    @patch("surveys.tasks.SyncLease.acquire", return_value=True)
    @patch("surveys.tasks.SurveyAttempt.objects.select_related")
    def test_reconciliation_queue_puts_never_checked_attempts_first(
        self, select_related, _acquire, _release
    ):
        pending = (
            select_related.return_value.filter.return_value.exclude.return_value
            .filter.return_value
        )
        pending.order_by.return_value.__getitem__.return_value = []

        result = reconcile_pending_attempts_task.run()

        checked_order, initiated_order = pending.order_by.call_args.args
        self.assertTrue(checked_order.nulls_first)
        self.assertFalse(checked_order.descending)
        self.assertTrue(initiated_order.descending)
        self.assertEqual(result, {"checked": 0, "terminal": 0, "failures": 0})

    def test_periodic_maintenance_tasks_do_not_persist_celery_results(self):
        self.assertTrue(dispatch_due_integrations_task.ignore_result)
        self.assertTrue(reconcile_pending_attempts_task.ignore_result)

    @override_settings(
        INNOVATEMR_ATTEMPT_RECONCILE_INTERVAL_SECONDS=60,
        INNOVATEMR_ATTEMPT_RECONCILE_LOOKBACK_HOURS=24,
        INNOVATEMR_ATTEMPT_RECONCILE_BATCH=20,
    )
    def test_reconciliation_closes_existing_sessions_when_a_later_client_fails(self):
        first_integration = self._integration("first-client")
        second_integration = self._integration("failing-client")
        now = timezone.now()
        first_survey = Survey.objects.create(
            client=first_integration.client,
            integration=first_integration,
            source_id=201,
            status=Survey.Status.LIVE,
        )
        second_survey = Survey.objects.create(
            client=second_integration.client,
            integration=second_integration,
            source_id=202,
            status=Survey.Status.LIVE,
        )
        SurveyAttempt.objects.create(
            rid="Rc9Ab1Cd2E",
            survey=first_survey,
            user_id="first-respondent",
            status=SurveyAttempt.Status.REDIRECTED,
            initiated_at=now,
        )
        SurveyAttempt.objects.create(
            rid="Rc8Ab1Cd2E",
            survey=second_survey,
            user_id="second-respondent",
            status=SurveyAttempt.Status.REDIRECTED,
            initiated_at=now - timedelta(minutes=1),
        )
        first_client = Mock()
        first_client.session = Mock()
        first_client.close.side_effect = RuntimeError("close failed")

        with (
            patch("surveys.tasks.SyncLease.acquire", return_value=True),
            patch("surveys.tasks.SyncLease.release") as release,
            patch("surveys.tasks.reconcile_attempt_status", return_value=False),
            patch(
                "surveys.tasks.InnovateMRClient",
                side_effect=[first_client, RuntimeError("client setup failed")],
            ),
        ):
            with self.assertRaisesMessage(RuntimeError, "client setup failed"):
                reconcile_pending_attempts_task.run()

        first_client.close.assert_called_once_with()
        release.assert_called_once_with("innovatemr-attempt-reconciliation")

    def test_legacy_sync_closes_its_batch_client_after_detail_refresh(self):
        integration = self._integration("legacy-sync")
        upstream_client = Mock()
        summary = SimpleNamespace(
            run_id=1,
            status="success",
            created=0,
            updated=0,
            unchanged=0,
            closed=0,
            detail_failures=0,
        )

        with (
            patch("surveys.tasks.SyncLease.acquire", return_value=True),
            patch("surveys.tasks.SyncLease.release") as release,
            patch("surveys.tasks.InnovateMRClient", return_value=upstream_client),
            patch("surveys.tasks.sync_surveys", return_value=summary),
        ):
            upstream_client.close.side_effect = RuntimeError("close failed")
            result = sync_client_integration_task.run(integration.pk)

        self.assertEqual(result["status"], "success")
        upstream_client.close.assert_called_once_with()
        release.assert_called_once_with(f"integration-{integration.pk}-sync")

    def test_stale_detail_refresh_ignores_cleanup_failure(self):
        ClientIntegration.objects.all().delete()
        self._integration("stale-details")
        upstream_client = Mock()
        upstream_client.close.side_effect = RuntimeError("close failed")

        with patch("surveys.tasks.InnovateMRClient", return_value=upstream_client):
            result = refresh_stale_details_task.run()

        self.assertEqual(result, {"refreshed": 0, "failures": 0})
        upstream_client.close.assert_called_once_with()
