import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen

from django.conf import settings


class FeedError(Exception):
    """Raised when an upstream survey feed cannot be used."""


_cache = {"data": None, "fetched_at": None, "monotonic": 0.0, "stale": False}
_supplier_cache = {"InnovateMR": None, "Voqall": None}
_voqall_language_cache = {}
_voqall_qualification_catalog_cache = {}
_voqall_question_detail_cache = {}
_question_cache = {}
_cache_lock = threading.Lock()
_question_cache_lock = threading.Lock()


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
        "language_id": str(_first(raw, "LanguageCode", "languageCode", default="")).strip(),
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
        "language_id": language_id,
        "placement_id": str(_first(raw, "PlacementId", "placementId", "placement_id", default="")).strip()
        or _query_value(entry_url, "placement_id"),
    }


def _request_json(url, headers, provider, timeout=None):
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "AlessarSurveyBoard/2.0",
            **headers,
        },
    )
    try:
        with urlopen(request, timeout=timeout or settings.SURVEY_FEED_TIMEOUT) as response:
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


def _normalize_question_option(raw):
    if not isinstance(raw, dict):
        value = str(raw).strip()
        return {"id": value, "text": value}
    option_id = str(_first(raw, "OptionId", "optionId", "Id", "id", "OptionCode", "optionCode", default="")).strip()
    text = _first(raw, "OptionText", "optionText", "Text", "text", "Name", "name")
    if text in (None, ""):
        age_start = _first(raw, "ageStart", "AgeStart")
        age_end = _first(raw, "ageEnd", "AgeEnd")
        if age_start not in (None, "") or age_end not in (None, ""):
            text = f"{age_start or ''}–{age_end or ''}".strip("–")
        else:
            text = option_id
    return {"id": option_id, "text": str(text).strip()}


def normalize_innovatemr_question(raw):
    question_id = str(_first(raw, "QuestionId", "questionId", "id", default="")).strip()
    code = str(_first(raw, "QuestionKey", "questionKey", "Code", "code", default="")).strip()
    text = str(_first(raw, "QuestionText", "questionText", "text", default=code or f"Question {question_id}")).strip()
    options = [_normalize_question_option(option) for option in (_first(raw, "Options", "options", default=[]) or [])]
    return {
        "id": question_id,
        "code": code,
        "text": text,
        "type": str(_first(raw, "QuestionType", "questionType", "TypeName", default="")).strip(),
        "category": str(_first(raw, "QuestionCategory", "questionCategory", "Category", default="")).strip(),
        "options": [option for option in options if option["text"]],
    }


def _fetch_innovatemr_questions(survey_id):
    token = settings.INNOVATEMR_ACCESS_TOKEN.strip()
    if not token:
        raise FeedError("InnovateMR is not configured.")
    url = f"{settings.INNOVATEMR_TARGETING_URL.rstrip('/')}/{quote(str(survey_id), safe='')}"
    payload = _request_json(
        url,
        {"x-access-token": token},
        "InnovateMR targeting",
        timeout=settings.SURVEY_QUESTION_TIMEOUT,
    )
    rows = _extract_rows(payload, ("result", "targeting", "questions", "data"), "InnovateMR targeting")
    return [normalize_innovatemr_question(row) for row in rows if isinstance(row, dict)]


def _fetch_voqall_qualification_catalog(access_key):
    global _voqall_qualification_catalog_cache
    if _voqall_qualification_catalog_cache:
        return _voqall_qualification_catalog_cache
    try:
        payload = _request_json(
            settings.VOQALL_QUALIFICATION_CATALOG_URL,
            {"EQ-PARTNER-ACCESS-KEY": access_key},
            "Voqall qualification catalog",
            timeout=settings.SURVEY_QUESTION_TIMEOUT,
        )
        rows = _extract_rows(payload, ("Qualifications", "qualifications", "data"), "Voqall qualification catalog")
        catalog = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            qualification_id = str(_first(row, "Id", "id", "QualificationId", default="")).strip()
            if qualification_id:
                catalog[qualification_id] = row
        if catalog:
            _voqall_qualification_catalog_cache = catalog
    except FeedError:
        pass
    return _voqall_qualification_catalog_cache


def _fetch_voqall_question_detail(access_key, language_id, qualification_id):
    cache_key = (str(language_id), str(qualification_id))
    with _question_cache_lock:
        cached = _voqall_question_detail_cache.get(cache_key)
    if cached is not None:
        return cached

    url = settings.VOQALL_QUALIFICATION_DETAIL_URL.format(
        language_id=quote(str(language_id), safe=""),
        qualification_id=quote(str(qualification_id), safe=""),
    )
    payload = _request_json(
        url,
        {"EQ-PARTNER-ACCESS-KEY": access_key},
        "Voqall qualification detail",
        timeout=settings.SURVEY_QUESTION_TIMEOUT,
    )
    detail = payload.get("Qualification") if isinstance(payload, dict) else None
    if not isinstance(detail, dict):
        raise FeedError("Voqall qualification detail returned an unexpected response.")
    with _question_cache_lock:
        _voqall_question_detail_cache[cache_key] = detail
    return detail


def _allowed_voqall_options(raw, detail):
    allowed_values = {
        str(value).strip()
        for value in ((_first(raw, "OptionIds", "optionIds", default=[]) or []) + (_first(raw, "OptionCodes", "optionCodes", default=[]) or []))
        if str(value).strip()
    }
    detail_options = _first(detail, "Options", "options", default=[]) or []
    normalized = []
    for option in detail_options:
        if not isinstance(option, dict):
            continue
        identifiers = {
            str(value).strip()
            for value in (
                _first(option, "Id", "id"),
                _first(option, "OptionId", "optionId"),
                _first(option, "OptionCode", "optionCode"),
            )
            if value not in (None, "")
        }
        if allowed_values and identifiers.isdisjoint(allowed_values):
            continue
        normalized.append(_normalize_question_option(option))
    if not normalized and allowed_values:
        normalized = [{"id": value, "text": value} for value in sorted(allowed_values)]
    return normalized


def _normalize_voqall_question(raw, detail, catalog):
    qualification_id = str(_first(raw, "QualificationId", "qualificationId", "Id", default="")).strip()
    fallback = catalog.get(qualification_id, {})
    source = detail or fallback
    code = str(_first(source, "Code", "code", default=f"Qualification {qualification_id}")).strip()
    return {
        "id": qualification_id,
        "code": code,
        "text": str(_first(source, "QuestionText", "questionText", default=code)).strip(),
        "type": str(_first(source, "TypeName", "typeName", default="")).strip(),
        "category": "Qualification",
        "options": _allowed_voqall_options(raw, detail or {}),
    }


def _fetch_voqall_questions(survey_id, language_id):
    access_key = settings.VOQALL_ACCESS_KEY.strip()
    if not access_key:
        raise FeedError("Voqall is not configured.")
    url = f"{settings.VOQALL_SURVEY_QUALIFICATIONS_URL.rstrip('/')}/{quote(str(survey_id), safe='')}"
    payload = _request_json(
        url,
        {"EQ-PARTNER-ACCESS-KEY": access_key},
        "Voqall qualifications",
        timeout=settings.SURVEY_QUESTION_TIMEOUT,
    )
    rows = _extract_rows(payload, ("Qualifications", "qualifications", "result", "data"), "Voqall qualifications")
    rows = [row for row in rows if isinstance(row, dict)]
    catalog = _fetch_voqall_qualification_catalog(access_key)

    details = {}
    qualification_ids = {
        str(_first(row, "QualificationId", "qualificationId", "Id", default="")).strip()
        for row in rows
    }
    qualification_ids.discard("")
    if language_id and qualification_ids:
        with ThreadPoolExecutor(max_workers=min(8, len(qualification_ids))) as executor:
            futures = {
                executor.submit(_fetch_voqall_question_detail, access_key, language_id, qualification_id): qualification_id
                for qualification_id in qualification_ids
            }
            for future in as_completed(futures):
                qualification_id = futures[future]
                try:
                    details[qualification_id] = future.result()
                except FeedError:
                    continue

    return [
        _normalize_voqall_question(
            row,
            details.get(str(_first(row, "QualificationId", "qualificationId", "Id", default="")).strip(), {}),
            catalog,
        )
        for row in rows
    ]


def get_survey_questions(survey, force=False):
    company = str(survey.get("company", "")).strip()
    survey_id = str(survey.get("survey_id", "")).strip()
    cache_key = (company.casefold(), survey_id)
    now = time.monotonic()
    with _question_cache_lock:
        cached = _question_cache.get(cache_key)
        if cached and not force and now - cached["monotonic"] < settings.SURVEY_QUESTION_CACHE_SECONDS:
            return cached["data"]

    if company.casefold() == "innovatemr":
        questions = _fetch_innovatemr_questions(survey_id)
    elif company.casefold() == "voqall":
        questions = _fetch_voqall_questions(survey_id, str(survey.get("language_id", "")).strip())
    else:
        raise FeedError("Question data is not supported for this supplier.")

    result = {
        "company": company,
        "survey_id": survey_id,
        "survey_name": survey.get("name") or "Untitled survey",
        "questions": questions,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    with _question_cache_lock:
        _question_cache[cache_key] = {"data": result, "monotonic": now}
    return result


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
