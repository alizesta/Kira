"""User-confirmed location for regional public-health news.

IP geolocation is only a suggestion: VPNs, proxies, mobile carriers and ISP
routing can point to the wrong city. Call detect_ip_location only from the
first-run confirmation flow; never silently persist its result.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from .config import load_settings, save_settings

_log = logging.getLogger(__name__)
_IP_GEOLOCATION_URL = "https://ipapi.co/json/"
_TIMEOUT_SECONDS = 4


def detect_ip_location() -> dict:
    """Return an unconfirmed city/country suggestion based on the public IP."""
    request = Request(
        _IP_GEOLOCATION_URL,
        headers={"User-Agent": "Kira-Desktop/1.0", "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            if response.status != 200:
                raise RuntimeError(f"IP geolocation returned HTTP {response.status}")
            payload = json.loads(response.read(256_000).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - location is optional and must never block startup
        _log.info("IP location suggestion unavailable: %s", exc)
        return {"city": "", "country": "", "source": "ip", "confirmed": False}

    city = str(payload.get("city") or "").strip()[:100]
    country = str(payload.get("country_name") or "").strip()[:100]
    if not city or not country:
        return {"city": "", "country": "", "source": "ip", "confirmed": False}
    return {"city": city, "country": country, "source": "ip", "confirmed": False}


def get_confirmed_location() -> dict:
    """Read the last user-confirmed city/country, or an empty location."""
    settings = load_settings()
    raw = settings.get("user_location")
    if not isinstance(raw, dict) or raw.get("confirmed") is not True:
        return {"city": "", "country": "", "source": "", "confirmed": False}
    city = str(raw.get("city") or "").strip()
    country = str(raw.get("country") or "").strip()
    if not city or not country:
        return {"city": "", "country": "", "source": "", "confirmed": False}
    return {**raw, "city": city, "country": country, "confirmed": True}


def confirm_location(city: str, country: str, *, source: str = "user") -> dict:
    """Persist a location only after the user confirms or manually enters it."""
    clean_city = str(city or "").strip()[:100]
    clean_country = str(country or "").strip()[:100]
    if not clean_city or not clean_country:
        raise ValueError("Both city and country are required")
    settings = load_settings()
    location = {
        "city": clean_city,
        "country": clean_country,
        "source": "user" if source == "user" else "ip_confirmed",
        "confirmed": True,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    settings["user_location"] = location
    save_settings(settings)
    return dict(location)


def clear_location() -> None:
    """Remove the saved location so the first-run confirmation can be shown again."""
    settings = load_settings()
    settings["user_location"] = {
        "city": "", "country": "", "source": "", "confirmed": False, "updated_at": ""
    }
    save_settings(settings)
