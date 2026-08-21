"""Small, dependency-free helpers for normalizing survey market labels."""

from __future__ import annotations


# Provider feeds do not always include ISO codes.  Keep the aliases explicit so
# filtering and target-country validation do not silently disappear when only a
# display name is supplied.
ISO2_BY_COUNTRY_NAME = {
    "argentina": "AR",
    "australia": "AU",
    "austria": "AT",
    "belgium": "BE",
    "brazil": "BR",
    "canada": "CA",
    "chile": "CL",
    "china": "CN",
    "colombia": "CO",
    "croatia": "HR",
    "czech republic": "CZ",
    "czechia": "CZ",
    "denmark": "DK",
    "egypt": "EG",
    "finland": "FI",
    "france": "FR",
    "germany": "DE",
    "greece": "GR",
    "hong kong": "HK",
    "hungary": "HU",
    "india": "IN",
    "indonesia": "ID",
    "ireland": "IE",
    "israel": "IL",
    "italy": "IT",
    "japan": "JP",
    "kenya": "KE",
    "luxembourg": "LU",
    "malaysia": "MY",
    "mexico": "MX",
    "netherlands": "NL",
    "new zealand": "NZ",
    "norway": "NO",
    "philippines": "PH",
    "poland": "PL",
    "portugal": "PT",
    "republic of korea": "KR",
    "romania": "RO",
    "russia": "RU",
    "saudi arabia": "SA",
    "singapore": "SG",
    "slovakia": "SK",
    "south africa": "ZA",
    "south korea": "KR",
    "spain": "ES",
    "sweden": "SE",
    "switzerland": "CH",
    "taiwan": "TW",
    "thailand": "TH",
    "turkey": "TR",
    "turkiye": "TR",
    "united arab emirates": "AE",
    "united kingdom": "GB",
    "united states": "US",
    "united states of america": "US",
    "vietnam": "VN",
}


def normalize_country_code(country_code: object = "", country_name: object = "") -> str:
    """Return a trusted ISO alpha-2 code or derive one from a known name."""

    supplied = str(country_code or "").strip().upper()
    if len(supplied) == 2 and supplied.isalpha():
        return supplied
    normalized_name = " ".join(str(country_name or "").strip().casefold().split())
    return ISO2_BY_COUNTRY_NAME.get(normalized_name, "")
