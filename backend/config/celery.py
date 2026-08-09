import os
import logging

from celery import Celery
from celery.signals import beat_init, worker_ready
from django.db.utils import OperationalError, ProgrammingError

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("survey_workspace")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

logger = logging.getLogger(__name__)


def _reconcile_innovatemr_credential_on_startup() -> None:
    try:
        from vendors.credentials import reconcile_all_integration_credentials

        result = reconcile_all_integration_credentials()
        if result["cleared"]:
            logger.warning("Integration credentials changed; cleared %s scoped surveys.", result["cleared"])
    except (OperationalError, ProgrammingError):
        logger.warning(
            "InnovateMR credential check deferred until database migrations are available.",
            exc_info=True,
        )


@beat_init.connect(weak=False)
def reconcile_innovatemr_credential_for_beat(**_kwargs) -> None:
    _reconcile_innovatemr_credential_on_startup()


@worker_ready.connect(weak=False)
def reconcile_innovatemr_credential_for_worker(**_kwargs) -> None:
    _reconcile_innovatemr_credential_on_startup()
