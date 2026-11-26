"""Best-effort one-time IP geolocation for the user's preferred health-news region.

Only city/region/country are returned. The public IP and coordinates are never
persisted. IP geolocation is approximate and may identify a VPN/proxy exit.
"""
from __future__ import annotations

import re

import requests

IP_GEOLOCATION_URL = "https://ipapi.co/json/"
_TIMEOUT = (2.5, 5.0)


def detect_ip_region(*, requester=None) -> dict | None:
    """Return a suggested city/country based on public IP, or None on any failure."""
    get = requester or requests.get
    try:
        response = get(
            IP_GEOLOCATION_URL,
            timeout=_TIMEOUT,
            headers={"User-Agent": "Kira-Desktop/1.0", "Accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        return None

    if not isinstance(payload, dict) or payload.get("error"):
        return None

    city = _clean(payload.get("city"))
    region = _clean(payload.get("region"))
    country = _clean(payload.get("country_name") or payload.get("country"))
    # The city is the useful epidemiological unit; include state/region when
    # present and distinct so similarly named cities are not conflated.
    locality = city
    if region and region.casefold() != city.casefold():
        locality = ", ".join(part for part in (city, region) if part)
    if country:
        locality = ", ".join(part for part in (locality, country) if part)
    if not locality:
        return None
    return {"region": locality[:160], "source": "ip_estimate"}


def _clean(value) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if text.casefold() in {"none", "null", "unknown", "n/a"}:
        return ""
    return "".join(ch for ch in text if ch.isprintable())[:80]
