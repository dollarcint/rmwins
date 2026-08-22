"""InnovateMR redirect hash verification.

InnovateMR signs the complete hydrated callback URL while leaving the ``hash``
query value empty. The production account is configured for HMAC-SHA1 with a
lowercase hexadecimal digest. Query ordering and escaping are therefore kept
byte-for-byte when reconstructing the signed value.
"""

import hashlib
import hmac
import re
from urllib.parse import unquote, unquote_plus, urlsplit


HASH_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")

UPSTREAM_STATUS_MAP = {
    "1": "1",  # complete
    "2": "2",  # client-side termination
    "3": "3",  # client-side over quota
    "4": "4",  # client-side quality/security termination
    "5": "2",  # pre-survey termination
    "7": "3",  # pre-survey over quota
    "8": "4",  # pre-survey quality/security termination
}


class CallbackConfigurationError(ValueError):
    """Raised when the server-side callback signing configuration is unsafe."""


def _validated_public_url(public_url: str) -> str:
    value = str(public_url or "").strip()
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or not parts.netloc
        or not parts.path
        or parts.query
        or parts.fragment
        or parts.username
        or parts.password
    ):
        raise CallbackConfigurationError(
            "INNOVATEMR_CALLBACK_PUBLIC_URL must be an HTTPS URL without a query or fragment."
        )
    return value


def unsigned_callback_url(public_url: str, raw_query: str) -> str:
    """Return the exact URL InnovateMR signed, with only ``hash`` emptied."""

    base_url = _validated_public_url(public_url)
    components = str(raw_query or "").split("&")
    hash_indexes = []
    for index, component in enumerate(components):
        raw_name, separator, _raw_value = component.partition("=")
        if separator and unquote_plus(raw_name) == "hash":
            hash_indexes.append(index)
    if len(hash_indexes) != 1:
        raise ValueError("The callback must contain exactly one hash value.")
    index = hash_indexes[0]
    raw_name = components[index].split("=", 1)[0]
    components[index] = f"{raw_name}="
    return f"{base_url}?{'&'.join(components)}"


def unsigned_callback_url_candidates(public_url: str, raw_query: str) -> tuple[str, ...]:
    """Return the exact and Innovate-normalized forms that may be signed.

    Innovate's browser redirect has been observed signing the hydrated
    ``termReason`` value before the browser percent-encodes spaces and other
    characters.  The exact wire representation remains the primary contract;
    the second candidate only decodes that one documented outcome value.
    """

    exact = unsigned_callback_url(public_url, raw_query)
    components = str(raw_query or "").split("&")
    normalized_components = []
    changed = False
    for component in components:
        raw_name, separator, raw_value = component.partition("=")
        if separator and unquote_plus(raw_name) == "termReason":
            normalized_value = unquote(raw_value)
            normalized_components.append(f"{raw_name}={normalized_value}")
            changed = changed or normalized_value != raw_value
        else:
            normalized_components.append(component)
    if not changed:
        return (exact,)
    base_url = _validated_public_url(public_url)
    normalized_query = "&".join(normalized_components)
    normalized = unsigned_callback_url(base_url, normalized_query)
    return (exact, normalized)


def expected_callback_hash(secret: str, unsigned_url: str) -> str:
    """Generate InnovateMR's configured HMAC-SHA1 lowercase hex digest."""

    key = str(secret or "").encode("utf-8")
    if not key:
        raise CallbackConfigurationError(
            "INNOVATEMR_CALLBACK_HASH_SECRET is not configured."
        )
    return hmac.new(key, unsigned_url.encode("utf-8"), hashlib.sha1).hexdigest()


def verify_callback_hash(*, secret: str, public_url: str, raw_query: str, received_hash: str) -> bool:
    """Verify one callback in constant time without logging secret material."""

    supplied = str(received_hash or "").strip()
    if not HASH_PATTERN.fullmatch(supplied):
        return False
    verified = False
    for unsigned_url in unsigned_callback_url_candidates(public_url, raw_query):
        expected = expected_callback_hash(secret, unsigned_url)
        verified |= hmac.compare_digest(expected, supplied.lower())
    return verified
