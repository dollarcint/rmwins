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
    """Raised when the upstream survey feed cannot be used."""


_cache = {"data": None, "fetched_at": None, "monotonic": 0.0}
_cache_lock = threading.Lock()


def _clean_payout(value):
    try:
        return float(Decimal(str(value)).quantize(Decimal("0.001")))
    except (InvalidOperation, TypeError, ValueError):
        return 0.0


def normalize_survey(raw):
    entry_url = str(raw.get("entry_url") or "")
    query = parse_qs(urlparse(entry_url).query)
    company = (query.get("company") or [""])[0].strip()
    placement_id = (query.get("placement_id") or [""])[0].strip()

    return {
        "survey_id": str(raw.get("survey_id") or "").strip(),
        "name": str(raw.get("name") or "Untitled survey").strip(),
        "payout": _clean_payout(raw.get("payout")),
        "description": raw.get("description") or "",
        "entry_url": entry_url,
        "country": str(raw.get("country") or "Unknown").strip().upper(),
        "company": company or "Unknown",
        "placement_id": placement_id,
    }


def _fetch_upstream():
    request = Request(
        settings.SURVEY_FEED_URL,
        headers={"Accept": "application/json", "User-Agent": "SurveyBoard/1.0"},
    )
    try:
        with urlopen(request, timeout=settings.SURVEY_FEED_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise FeedError("The live survey provider is temporarily unavailable.") from exc

    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise FeedError("The survey provider returned an unexpected response.")

    return [normalize_survey(row) for row in rows if isinstance(row, dict)]


def get_surveys(force=False):
    """Return normalized live surveys with a short cache and stale fallback."""
    now = time.monotonic()
    with _cache_lock:
        age = now - _cache["monotonic"]
        if not force and _cache["data"] is not None and age < settings.SURVEY_CACHE_SECONDS:
            return _cache["data"], _cache["fetched_at"], False

        try:
            surveys = _fetch_upstream()
            fetched_at = datetime.now(timezone.utc)
            _cache.update(data=surveys, fetched_at=fetched_at, monotonic=now)
            return surveys, fetched_at, False
        except FeedError:
            if _cache["data"] is not None:
                return _cache["data"], _cache["fetched_at"], True
            raise
