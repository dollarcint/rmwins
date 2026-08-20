"""Celery application bootstrap and worker credential startup audit."""

import logging
import os

from celery import Celery
from celery.signals import worker_ready


logger = logging.getLogger(__name__)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("survey_workspace")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


def reconcile_credentials_on_startup(**kwargs):
    """Baseline/detect environment-backed credentials when a worker starts."""
    try:
        from vendors.credentials import reconcile_all_integration_credentials
        reconcile_all_integration_credentials()
    except Exception:
        # Database tables may not exist yet during first deploy/migration.
        logger.warning("Could not reconcile integration credentials at worker startup", exc_info=True)


worker_ready.connect(reconcile_credentials_on_startup, weak=False)
