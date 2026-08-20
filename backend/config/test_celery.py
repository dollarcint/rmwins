"""Celery bootstrap regression tests."""

from unittest.mock import patch

from celery.signals import beat_init, worker_ready
from django.test import SimpleTestCase

from .celery import reconcile_credentials_on_startup


class CeleryBootstrapTests(SimpleTestCase):
    def test_credentials_are_reconciled_by_workers_not_the_scheduler(self):
        worker_receivers = [receiver for _key, receiver in worker_ready.receivers]
        beat_receivers = [receiver for _key, receiver in beat_init.receivers]

        self.assertIn(reconcile_credentials_on_startup, worker_receivers)
        self.assertNotIn(reconcile_credentials_on_startup, beat_receivers)

    @patch("vendors.credentials.reconcile_all_integration_credentials")
    def test_worker_startup_runs_the_credential_audit(self, reconcile):
        reconcile_credentials_on_startup()

        reconcile.assert_called_once_with()

    @patch("config.celery.logger.warning")
    @patch(
        "vendors.credentials.reconcile_all_integration_credentials",
        side_effect=RuntimeError("database unavailable"),
    )
    def test_startup_failure_is_visible_without_crashing_the_worker(self, _reconcile, warning):
        reconcile_credentials_on_startup()

        warning.assert_called_once()
