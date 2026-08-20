"""Small cache-backed protections for expensive public authentication work."""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import unicodedata

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import RequestDataTooBig


logger = logging.getLogger(__name__)


def _request_ip(request) -> str:
    """Return the proxy-supplied client IP only when that proxy is trusted."""

    candidates = []
    if settings.TRUST_X_FORWARDED_FOR:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            candidates.append(forwarded.split(",", 1)[0].strip())
    candidates.append(request.META.get("REMOTE_ADDR", ""))

    for candidate in candidates:
        try:
            return ipaddress.ip_address(candidate).compressed
        except ValueError:
            continue
    return "unknown"


def _login_ip_attempt_key(request) -> str:
    fingerprint = hashlib.sha256(_request_ip(request).encode("utf-8")).hexdigest()
    return f"auth-login-ip:{fingerprint}"


def normalize_login_username(username: str) -> str:
    """Match Django's compatibility normalization before case-folding keys."""

    return unicodedata.normalize("NFKC", str(username or "")).strip().casefold()


def _login_account_attempt_key(username: str) -> str:
    normalized = normalize_login_username(username)
    fingerprint = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"auth-login-account:{fingerprint}"


def login_request_body_too_large(request) -> bool:
    """Reject oversized login bodies before Django parses form or JSON data."""

    try:
        declared_length = int(request.META.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        declared_length = 0
    if declared_length > settings.AUTH_LOGIN_MAX_BODY_BYTES:
        return True
    try:
        return len(request.body) > settings.AUTH_LOGIN_MAX_BODY_BYTES
    except RequestDataTooBig:
        return True


def _consume_attempt(key: str, limit: int, window: int) -> bool:
    if cache.add(key, 1, timeout=window):
        return True
    try:
        attempts = cache.incr(key)
    except ValueError:
        # The entry can expire between add() and incr(). Retry the atomic
        # initialization once before falling back to another increment.
        if cache.add(key, 1, timeout=window):
            return True
        attempts = cache.incr(key)
    return attempts <= limit


def consume_login_attempt(request, username: str) -> bool:
    """Reserve one password check in both IP and normalized-account buckets.

    Production uses shared Redis, while development's local-memory cache still
    provides a useful per-process guard. The proxy has an independent limiter,
    so a transient cache outage is allowed to fail open instead of taking login
    completely offline.
    """

    window = settings.AUTH_LOGIN_WINDOW_SECONDS
    try:
        ip_allowed = _consume_attempt(
            _login_ip_attempt_key(request),
            settings.AUTH_LOGIN_MAX_IP_ATTEMPTS,
            window,
        )
        account_allowed = _consume_attempt(
            _login_account_attempt_key(username),
            settings.AUTH_LOGIN_MAX_ATTEMPTS,
            window,
        )
        return ip_allowed and account_allowed
    except Exception:  # pragma: no cover - backend-specific outage path
        logger.exception("Login rate-limit cache is unavailable")
        return True


def reset_login_account_attempts(username: str) -> None:
    """Clear only the authenticated account bucket; the IP guard stays monotonic."""

    try:
        cache.delete(_login_account_attempt_key(username))
    except Exception:  # pragma: no cover - backend-specific outage path
        logger.warning("Unable to clear account login rate-limit cache", exc_info=True)
