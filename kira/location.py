"""One-time region discovery for Mika's local public-health feed.

Windows device location is preferred when the optional WinRT projection is
installed and the user grants Windows permission. IP geolocation is the
fallback. Only the confirmed city/region/country is persisted; raw IPs and
coordinates are never stored.
"""
from __future__ import annotations

import asyncio
import re
import sys

import requests

IP_GEOLOCATION_URL = "https://ipapi.co/json/"
REVERSE_GEOCODE_URL = "https://nominatim.openstreetmap.org/reverse"
_TIMEOUT = (2.5, 5.0)


def request_windows_location_permission(on_result):
    """Start Windows' native permission prompt on the calling UI thread.

    The returned WinRT operation is retained by the caller. Completion is
    delivered through the callback, which may run on a WinRT worker thread.
    """
    if sys.platform != "win32":
        return None
    try:
        from winrt.windows.devices.geolocation import Geolocator
        operation = Geolocator.request_access_async()
    except (ImportError, AttributeError, OSError, RuntimeError):
        return None

    def completed(op, _status):
        try:
            access = op.get_results()
            allowed = "allowed" in str(access).casefold()
        except Exception:
            allowed = False
        try:
            on_result(bool(allowed))
        except Exception:
            pass

    try:
        operation.completed = completed
    except (AttributeError, TypeError, RuntimeError):
        return None
    # Retain the WinRT async operation until its completion callback fires.
    return operation


def detect_windows_region(*, reverse_requester=None) -> dict | None:
    """Read the current Windows device location and reverse-geocode it to a city."""
    if sys.platform != "win32":
        return None
    try:
        from winrt.windows.devices.geolocation import Geolocator

        async def get_coordinates():
            locator = Geolocator()
            position = await asyncio.wait_for(locator.get_geoposition_async(), timeout=10)
            point = position.coordinate.point.position
            return float(point.latitude), float(point.longitude)

        latitude, longitude = asyncio.run(get_coordinates())
    except Exception:
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None

    get = reverse_requester or requests.get
    try:
        response = get(
            REVERSE_GEOCODE_URL,
            params={
                "lat": latitude,
                "lon": longitude,
                "format": "jsonv2",
                "zoom": 10,
                "addressdetails": 1,
            },
            timeout=_TIMEOUT,
            headers={
                "User-Agent": "Kira-Desktop/1.0 (one-time health-news region setup)",
                "Accept": "application/json",
            },
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        return None

    address = payload.get("address") if isinstance(payload, dict) else None
    if not isinstance(address, dict):
        return None
    city = next(
        (_clean(address.get(key)) for key in ("city", "town", "municipality", "village", "county") if _clean(address.get(key))),
        "",
    )
    region = _clean(address.get("state") or address.get("region"))
    country = _clean(address.get("country"))
    locality = city
    if region and region.casefold() != city.casefold():
        locality = ", ".join(part for part in (city, region) if part)
    if country:
        locality = ", ".join(part for part in (locality, country) if part)
    if not locality:
        return None
    return {"region": locality[:160], "source": "windows_location"}


def detect_ip_region(*, requester=None) -> dict | None:
    """Return a suggested city/country from public IP, or None on any failure."""
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
