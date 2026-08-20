"""Shared provider adapter contract, normalized DTO and safe configuration errors."""

import logging
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests


ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
logger = logging.getLogger(__name__)


class ProviderError(RuntimeError):
    """Safe upstream/provider error suitable for operational audit logs."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class ProviderConfigurationError(ProviderError):
    """Raised when an integration references missing or invalid environment configuration."""


@dataclass(frozen=True)
class NormalizedSurvey:
    source_key: str
    numeric_source_id: int | None
    modified_at: datetime | None
    values: dict[str, Any]
    raw_data: dict[str, Any]


def environment_value(reference: str, label: str) -> str:
    """Resolve a validated environment-variable reference without exposing it."""

    reference = str(reference or "").strip()
    if not reference or not ENV_NAME_RE.fullmatch(reference):
        raise ProviderConfigurationError(f"Configure a valid environment-variable name for {label}.")
    value = os.getenv(reference, "")
    if not value:
        raise ProviderConfigurationError(f"Environment variable {reference} is not configured.")
    return value


def close_provider(provider) -> None:
    """Best-effort cleanup for a provider owned by the current operation."""

    close = getattr(provider, "close", None)
    if not callable(close):
        return
    try:
        close()
    except Exception:
        # Cleanup must never replace an upstream error or a successful business
        # result. Real adapters suppress their own close errors; this guard also
        # protects older/test adapters that have not adopted that contract yet.
        logger.warning("Could not close a survey provider", exc_info=True)


@contextmanager
def managed_provider(provider):
    """Yield an operation-owned provider and release it without masking results."""

    try:
        yield provider
    finally:
        close_provider(provider)


class SurveyProvider:
    """Interface implemented by specialized inventory/respondent providers."""

    code = "base"
    label = "Survey provider"
    minimum_sync_interval_seconds = 60
    credential_fields: tuple[tuple[str, str], ...] = ()
    default_base_url = ""
    close_missing_inventory_items = True

    def __init__(self, integration, *, session=None):
        self.integration = integration
        self._session = session
        self._owns_session = session is None
        self._closed = False

    @property
    def session(self) -> requests.Session:
        """Create an owned connection pool only when the provider performs I/O."""

        # A provider may expose a caller-supplied session after its own
        # lifecycle ends (for example, for request inspection or reuse). Only
        # an internally-owned pool becomes inaccessible once it is closed.
        if self._closed and self._owns_session:
            raise ProviderError("This provider client is already closed.")
        if self._session is None:
            self._session = requests.Session()
        return self._session

    def close(self) -> None:
        """Idempotently release only the HTTP session created by this provider."""

        if self._closed:
            return
        self._closed = True
        if not self._owns_session or self._session is None:
            return
        try:
            self._session.close()
        except Exception:
            logger.warning("Could not close a provider HTTP session", exc_info=True)

    def __enter__(self):
        if self._closed:
            raise ProviderError("This provider client is already closed.")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def test_connection(self) -> dict[str, Any]:
        raise NotImplementedError

    def inventory(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def normalize_inventory_item(self, payload: dict[str, Any], seen_at) -> NormalizedSurvey:
        raise NotImplementedError

    def prepare_inventory_item(self, normalized: NormalizedSurvey, existing_survey=None) -> NormalizedSurvey:
        """Perform provider work required before an inventory row may be persisted."""

        return normalized

    def refresh_details(self, survey) -> None:
        raise NotImplementedError

    def duplicate_check(self, survey, attempt, ip_address: str | None) -> bool:
        """Return provider duplicate state; providers without a check fail open."""

        return False

    def build_outbound_url(self, survey, attempt, answers: dict[str, Any]) -> str:
        raise NotImplementedError
