import json
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from django.conf import settings


class FeedError(Exception):
    """Raised when an upstream survey feed cannot be used."""


_cache = {"data": None, "fetched_at": None, "monotonic": 0.0, "stale": False}
_supplier_cache = {"InnovateMR": None, "Voqall": None}
_voqall_language_cache = {}
_cache_lock = threading.Lock()


def _clean_payout(value):
    try:
        return float(Decimal(str(value)).quantize(Decimal("0.001")))
    except (InvalidOperation, TypeError, ValueError):
        return 0.0


def _first(raw, *keys, default=None):
    for key in keys:
        value = raw.get(key)
        if value is not None and value != "":
            return value
    return default


def _query_value(entry_url, *keys):
    query = parse_qs(urlparse(entry_url).query)
    folded = {key.casefold(): values for key, values in query.items()}
    for key in keys:
        values = folded.get(key.casefold())
        if values:
            return str(values[0]).strip()
    return ""


def _description(raw):
    parts = []
    loi = _first(raw, "LOI", "Loi", "loi", "LengthOfInterview", "lengthOfInterview")
    ir = _first(raw, "IR", "Ir", "ir", "IncidentRate", "incidentRate")
    if loi not in (None, ""):
        parts.append(f"LOI: {loi} min")
    if ir not in (None, ""):
        parts.append(f"IR: {ir}%")
    return " · ".join(parts)


def normalize_innovatemr_survey(raw):
    entry_url = str(_first(raw, "entryLink", "entry_url", "entryUrl", default=""))
    return {
        "survey_id": str(_first(raw, "surveyId", "survey_id", "id", default="")).strip(),
        "name": str(_first(raw, "surveyName", "name", "title", default="Untitled survey")).strip(),
        "payout": _clean_payout(_first(raw, "CPI", "cpi", "supplierCPI", "supplierCpi", default=0)),
        "description": _description(raw),
        "entry_url": entry_url,
        "country": str(_first(raw, "CountryCode", "countryCode", "country", "Country", default="Unknown")).strip().upper(),
        "company": "InnovateMR",
        "placement_id": str(_first(raw, "placementId", "placement_id", default="")).strip()
        or _query_value(entry_url, "placement_id"),
    }


def normalize_voqall_survey(raw, languages=None):
    languages = languages or {}
    entry_url = str(_first(raw, "SurveyUrl", "surveyUrl", "entryLink", "entry_url", "url", default=""))
    language_id = str(_first(raw, "LanguageId", "languageId", default="")).strip()
    country = _first(raw, "CountryCode", "countryCode", "country", "Country")
    if not country and language_id:
        country = languages.get(language_id)

    return {
        "survey_id": str(_first(raw, "SurveyId", "surveyId", "survey_id", "id", default="")).strip(),
        "name": str(_first(raw, "Name", "surveyName", "survey_name", "name", default="Untitled survey")).strip(),
        "payout": _clean_payout(_first(raw, "Revenue", "revenue", "Cpi", "CPI", "cpi", default=0)),
        "description": _description(raw),
        "entry_url": entry_url,
        "country": str(country or "Unknown").strip().upper(),
        "company": "Voqall",
        "placement_id": str(_first(raw, "PlacementId", "placementId", "placement_id", default="")).strip()
        or _query_value(entry_url, "placement_id"),
    }


def _request_json(url, headers, provider):
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "AlessarSurveyBoard/2.0",
            **headers,
        },
    )
    try:
        with urlopen(request, timeout=settings.SURVEY_FEED_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8-sig"))
    except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FeedError(f"{provider} is temporarily unavailable.") from exc


def _extract_rows(payload, keys, provider):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        raise FeedError(f"{provider} returned an unexpected response.")
    if payload.get("hasError") is True or str(payload.get("apiStatus", "success")).casefold() in {"error", "failed", "failure"}:
        raise FeedError(f"{provider} rejected the inventory request.")

    folded = {str(key).casefold(): value for key, value in payload.items()}
    for key in keys:
        rows = folded.get(key.casefold())
        if isinstance(rows, list):
            return rows
    raise FeedError(f"{provider} returned an unexpected response.")


def _fetch_innovatemr_surveys():
    token = settings.INNOVATEMR_ACCESS_TOKEN.strip()
    if not token:
        raise FeedError("InnovateMR is not configured.")
    payload = _request_json(
        settings.INNOVATEMR_SURVEY_URL,
        {"x-access-token": token},
        "InnovateMR",
    )
    rows = _extract_rows(payload, ("result", "surveys", "data"), "InnovateMR")
    surveys = [normalize_innovatemr_survey(row) for row in rows if isinstance(row, dict)]
    return [survey for survey in surveys if survey["survey_id"] and survey["entry_url"]]


def _fetch_voqall_languages(access_key):
    global _voqall_language_cache
    if _voqall_language_cache:
        return _voqall_language_cache
    try:
        payload = _request_json(
            settings.VOQALL_LANGUAGES_URL,
            {"EQ-PARTNER-ACCESS-KEY": access_key},
            "Voqall markets",
        )
        rows = _extract_rows(payload, ("Languages", "languages", "data"), "Voqall markets")
        languages = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            language_id = str(_first(row, "Id", "id", "LanguageId", default="")).strip()
            country = str(_first(row, "CountryCode", "countryCode", "Name", "name", default="")).strip().upper()
            if language_id and country:
                languages[language_id] = country
        if languages:
            _voqall_language_cache = languages
    except FeedError:
        pass
    return _voqall_language_cache


def _fetch_voqall_surveys():
    access_key = settings.VOQALL_ACCESS_KEY.strip()
    if not access_key:
        raise FeedError("Voqall is not configured.")
    payload = _request_json(
        settings.VOQALL_SURVEY_URL,
        {"EQ-PARTNER-ACCESS-KEY": access_key},
        "Voqall",
    )
    rows = _extract_rows(payload, ("Surveys", "surveys", "result", "data"), "Voqall")
    languages = _fetch_voqall_languages(access_key)
    surveys = [normalize_voqall_survey(row, languages) for row in rows if isinstance(row, dict)]
    return [survey for survey in surveys if survey["survey_id"] and survey["entry_url"]]


def get_surveys(force=False):
    """Return both supplier inventories with short caching and per-supplier fallback."""
    now = time.monotonic()
    with _cache_lock:
        age = now - _cache["monotonic"]
        if not force and _cache["data"] is not None and age < settings.SURVEY_CACHE_SECONDS:
            return _cache["data"], _cache["fetched_at"], _cache["stale"]

        combined = []
        failed = []
        live_suppliers = 0
        for name, fetcher in (
            ("InnovateMR", _fetch_innovatemr_surveys),
            ("Voqall", _fetch_voqall_surveys),
        ):
            try:
                rows = fetcher()
                _supplier_cache[name] = rows
                combined.extend(rows)
                live_suppliers += 1
            except FeedError:
                failed.append(name)
                cached_rows = _supplier_cache.get(name)
                if cached_rows is not None:
                    combined.extend(cached_rows)

        if live_suppliers == 0 and not combined:
            if _cache["data"] is not None:
                return _cache["data"], _cache["fetched_at"], True
            raise FeedError("No live supplier feed could be reached. Check the supplier API environment variables.")

        fetched_at = datetime.now(timezone.utc)
        stale = bool(failed)
        _cache.update(data=combined, fetched_at=fetched_at, monotonic=now, stale=stale)
        return combined, fetched_at, stale
