"""Enligne hosted-feed adapter backed by read-only Lakshaya LMS metadata."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pymysql
import requests
from django.utils import timezone

from surveys.integrations import InnovateMRAPIError, InnovateMRClient
from surveys.models import Survey
from surveys.services import replace_survey_details
from vendors.models import ClientIntegration

from .base import (
    NormalizedSurvey,
    ProviderConfigurationError,
    ProviderError,
    SurveyProvider,
    environment_value,
)


class EnligneProvider(SurveyProvider):
    """Match Enligne LMS feed IDs to InnovateMR survey IDs without writing Lakshaya."""

    code = "enligne"
    label = "Enligne hosted InnovateMR"
    default_base_url = "https://enlignesurvey.com/get/api_feed/"
    minimum_sync_interval_seconds = 30
    credential_fields = (("db_password", "Lakshaya DB password environment key"),)

    def __init__(self, integration, *, session=None, db_connect=None, detail_client=None):
        super().__init__(integration, session=session or requests.Session())
        self.feed_url = str(integration.base_url or "").strip()
        parsed = urlsplit(self.feed_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in {"enlignesurvey.com", "www.enlignesurvey.com"}
            or not re.fullmatch(r"/get/api_feed/[A-Za-z0-9-]+/?", parsed.path)
            or parsed.query
            or parsed.fragment
        ):
            raise ProviderConfigurationError(
                "Enligne feed URL must be an HTTPS /get/api_feed/<feed-id> URL on enlignesurvey.com."
            )

        config = integration.config or {}
        self.timeout = max(5, min(int(config.get("timeout_seconds", 30)), 120))
        self.db_host = str(config.get("db_host") or "127.0.0.1").strip()
        self.db_port = int(config.get("db_port") or 3306)
        self.db_name = str(config.get("db_name") or "lakshaya").strip()
        self.db_user = str(config.get("db_user") or "").strip()
        self.db_password = environment_value(
            integration.credential_env_key,
            "Enligne Lakshaya DB password",
        )
        self.company_filter = str(config.get("company_filter") or "innovatemr").strip().lower()
        self.outbound_user_id = str(config.get("outbound_user_id") or "kanik").strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", self.db_name):
            raise ProviderConfigurationError("Enligne DB name is invalid.")
        if not self.db_user:
            raise ProviderConfigurationError("Configure the Enligne DB user.")
        if not re.fullmatch(r"[A-Za-z0-9_.@-]+", self.outbound_user_id):
            raise ProviderConfigurationError("Enligne outbound user_id is invalid.")
        if self.company_filter not in {"innovatemr", "voqall", "prime"}:
            raise ProviderConfigurationError("Enligne company filter is invalid.")
        self.db_connect = db_connect or pymysql.connect
        self.detail_client = detail_client
        self.inventory_failures = []

    def _innovate_client(self):
        """Resolve the original InnovateMR API only for enrichment/details."""

        if self.detail_client is not None:
            return self.detail_client
        configured_id = (self.integration.config or {}).get("detail_integration_id")
        integrations = ClientIntegration.objects.filter(
            client_id=self.integration.client_id,
            provider_code="innovatemr",
        ).exclude(pk=self.integration.pk)
        if configured_id:
            integrations = integrations.filter(pk=configured_id)
        detail_integration = integrations.order_by("pk").first()
        if detail_integration is None:
            raise ProviderConfigurationError(
                "Enligne requires the client's original InnovateMR API integration for details."
            )
        self.detail_client = InnovateMRClient(integration=detail_integration)
        return self.detail_client

    def _innovate_inventory(self):
        """Index live InnovateMR metadata without using it as inventory authority."""

        try:
            rows = self._innovate_client().get_allocated_surveys()
        except InnovateMRAPIError as exc:
            raise ProviderError("InnovateMR enrichment request failed.") from exc
        return {
            str(row.get("surveyId") or "").strip(): self._json_safe(row)
            for row in rows
            if str(row.get("surveyId") or "").strip()
        }

    def _connection(self):
        """Open a short-lived DB connection; all adapter SQL is SELECT-only."""

        try:
            return self.db_connect(
                host=self.db_host,
                port=self.db_port,
                user=self.db_user,
                password=self.db_password,
                database=self.db_name,
                charset="utf8mb4",
                connect_timeout=self.timeout,
                read_timeout=self.timeout,
                cursorclass=pymysql.cursors.DictCursor,
            )
        except pymysql.MySQLError as exc:
            raise ProviderError("Enligne Lakshaya database connection failed.") from exc

    @staticmethod
    def _json_safe(value):
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, dict):
            return {str(key): EnligneProvider._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [EnligneProvider._json_safe(item) for item in value]
        return value

    @staticmethod
    def _parse_datetime(raw):
        if raw is None or raw == "":
            return None
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed)
            return parsed
        except (TypeError, ValueError):
            return None

    def _feed_rows(self):
        try:
            response = self.session.get(
                self.feed_url,
                headers={"Accept": "application/json"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise ProviderError("Enligne feed request failed.") from exc
        except ValueError as exc:
            raise ProviderError("Enligne feed returned invalid JSON.") from exc
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ProviderError("Enligne feed response must contain a data list.")
        return [
            row for row in rows
            if isinstance(row, dict) and re.fullmatch(r"LMS-\d+", str(row.get("survey_id") or ""))
        ]

    def _lms_records(self, lms_ids):
        """Read matching LMS metadata in bounded SELECT-only batches."""

        records = {}
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                for offset in range(0, len(lms_ids), 500):
                    chunk = lms_ids[offset:offset + 500]
                    if not chunk:
                        continue
                    placeholders = ",".join(["%s"] * len(chunk))
                    cursor.execute(
                        "SELECT lms_survey_id, survey_id, survey_company, survey_name, "
                        "surveyLocalization, cpi, loi, ir, survey_status, status, "
                        "createdAt, updatedAt FROM LMS_Model "
                        f"WHERE lms_survey_id IN ({placeholders})",
                        chunk,
                    )
                    for row in cursor.fetchall():
                        key = str(row.get("lms_survey_id") or "").strip()
                        if key:
                            records[key] = self._json_safe(row)
        except pymysql.MySQLError as exc:
            raise ProviderError("Enligne LMS metadata lookup failed.") from exc
        finally:
            connection.close()
        return records

    def inventory(self):
        """Fetch the feed and join its LMS IDs to actual InnovateMR survey IDs."""

        feed_rows = self._feed_rows()
        lms_ids = list(dict.fromkeys(str(row["survey_id"]) for row in feed_rows))
        records = self._lms_records(lms_ids)
        innovate_inventory = self._innovate_inventory()
        inventory = []
        self.inventory_failures = []
        for row in feed_rows:
            lms_id = str(row["survey_id"])
            metadata = records.get(lms_id)
            if not metadata:
                self.inventory_failures.append({"lms_survey_id": lms_id, "reason": "not_found"})
                continue
            if str(metadata.get("survey_company") or "").strip().lower() != self.company_filter:
                continue
            actual_survey_id = str(metadata.get("survey_id") or "").strip()
            if not actual_survey_id:
                self.inventory_failures.append({"lms_survey_id": lms_id, "reason": "missing_survey_id"})
                continue
            inventory.append({
                **self._json_safe(row),
                "_lms": metadata,
                "_innovate": innovate_inventory.get(actual_survey_id, {}),
            })
        return inventory

    def test_connection(self):
        inventory = self.inventory()
        return {
            "provider": self.code,
            "authenticated": True,
            "matched_surveys": len(inventory),
            "unmatched_lms_ids": len(self.inventory_failures),
            "company_filter": self.company_filter,
            "database_mode": "select_only",
        }

    @staticmethod
    def _decimal(value):
        try:
            return Decimal(str(value)) if value not in (None, "") else None
        except (InvalidOperation, TypeError, ValueError):
            return None

    @staticmethod
    def _integer(value):
        try:
            return max(0, int(float(value))) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    @classmethod
    def _money(cls, value):
        amount = cls._decimal(value)
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if amount is not None else None

    def _hosted_link(self, value, track_id: str = ""):
        parts = urlsplit(str(value or "").strip())
        if parts.scheme != "https" or parts.hostname not in {"enlignesurvey.com", "www.enlignesurvey.com"}:
            raise ProviderError("Enligne feed supplied an invalid hosted entry URL.")
        query = []
        has_user_id = False
        for key, item in parse_qsl(parts.query, keep_blank_values=True):
            if key.lower() == "user_id":
                query.append((key, self.outbound_user_id))
                has_user_id = True
            elif key.lower() in {"trackid", "lid"}:
                if track_id:
                    continue
                query.append((key, item))
            else:
                query.append((key, item))
        if not has_user_id:
            query.append(("user_id", self.outbound_user_id))
        if track_id:
            query.append(("trackId", track_id))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))

    def normalize_inventory_item(self, payload, seen_at):
        metadata = payload.get("_lms") if isinstance(payload.get("_lms"), dict) else {}
        innovate = payload.get("_innovate") if isinstance(payload.get("_innovate"), dict) else {}
        source_key = str(metadata.get("survey_id") or "").strip()
        if not source_key:
            raise ProviderError("Enligne LMS metadata is missing the actual survey ID.")
        lms_id = str(payload.get("survey_id") or "").strip()
        country_code = str(payload.get("country") or metadata.get("surveyLocalization") or "").strip().upper()
        country_name = str(innovate.get("Country") or country_code).strip()
        loi = self._integer(metadata.get("loi"))
        ir = self._decimal(metadata.get("ir"))
        created_at = self._parse_datetime(metadata.get("createdAt"))
        modified = self._parse_datetime(metadata.get("updatedAt")) or created_at
        raw_data = {
            "feed": {key: value for key, value in payload.items() if key not in {"_lms", "_innovate"}},
            "lms": metadata,
            "innovatemr": innovate,
            "lms_survey_id": lms_id,
            "actual_survey_id": source_key,
            "adapter": "enligne_innovatemr_v2",
            "createdDate": metadata.get("createdAt"),
            "modifiedDate": metadata.get("updatedAt"),
            "source_created_at": created_at.isoformat() if created_at else None,
            "source_modified_at": modified.isoformat() if modified else None,
        }
        return NormalizedSurvey(
            source_key=source_key,
            numeric_source_id=int(source_key) if source_key.isdigit() else None,
            modified_at=modified,
            raw_data=raw_data,
            values={
                "company_name": "InnovateMR",
                "name": str(metadata.get("survey_name") or payload.get("name") or "Enligne Survey"),
                "status": Survey.Status.LIVE,
                "sample_size": self._integer(innovate.get("N")) or 0,
                "completes": self._integer(innovate.get("supCmps")) or 0,
                "remaining": self._integer(innovate.get("remainingN")) or 0,
                "starts": self._integer(innovate.get("numberOfStarts")) or 0,
                "cpi": self._money(payload.get("payout")),
                "loi": loi,
                "incidence_rate": ir,
                "country": country_name,
                "country_code": country_code,
                "language": str(innovate.get("Language") or ""),
                "language_code": str(innovate.get("LanguageCode") or "").upper(),
                "group_type": str(innovate.get("groupType") or ""),
                "buyer_id": str(innovate.get("BuyerId") or innovate.get("buyerId") or ""),
                "device_type": str(innovate.get("deviceType") or ""),
                "has_quota": bool(innovate.get("isQuota")),
                "entry_link": self._hosted_link(payload.get("entry_url")),
                "source_created_at": created_at,
                "source_modified_at": modified,
                "last_seen_at": seen_at,
                "detail_synced_at": None,
                "quota_synced_at": None,
                "targeting_synced_at": None,
                "raw_data": raw_data,
            },
        )

    def prepare_inventory_item(self, normalized, existing_survey=None):
        # Detail timestamps describe the feed/DB snapshot, not the current sync
        # clock. Preserve them so unchanged rows remain unchanged on later runs.
        if (
            existing_survey is not None
            and (existing_survey.raw_data or {}).get("adapter") == "enligne_innovatemr_v2"
        ):
            for field in ("detail_synced_at", "quota_synced_at", "targeting_synced_at"):
                normalized.values[field] = getattr(existing_survey, field) or normalized.values[field]
        return normalized

    def refresh_details(self, survey):
        replace_survey_details(self._innovate_client(), survey)

    def build_outbound_url(self, survey, attempt, answers):
        """Use the Enligne hosted link with fixed user_id=kanik and attempt RID tracking."""

        return self._hosted_link(survey.entry_link, track_id=attempt.rid)
