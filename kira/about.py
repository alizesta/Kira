"""About-section data: the version plus the build stamp shown to the user.

The values come from `kira/build_info.py`, which `scripts/build_metadata.py` rewrites on every build
and release (date, time and the auto-detected developer). Nothing here is hand-edited, and the module
has no Qt or config side effects, so both the GUI and the portable tests can use it.
"""
from __future__ import annotations

FALLBACK = "unknown"

#: Translation keys (kira/strings.py) for the About rows, in display order.
ROW_KEYS = ("about_version", "about_build_date", "about_build_time", "about_developer")


def build_stamp() -> dict[str, str]:
    """Return the recorded build stamp, or `unknown` values when the generated module is absent."""
    try:
        from . import build_info
    except Exception:                                    # a source checkout before the first build
        build_info = None
    return {
        "build_date": str(getattr(build_info, "BUILD_DATE", FALLBACK) or FALLBACK),
        "build_time": str(getattr(build_info, "BUILD_TIME", FALLBACK) or FALLBACK),
        "developer": str(getattr(build_info, "DEVELOPER", FALLBACK) or FALLBACK),
    }


def about_rows(version) -> list[tuple[str, str]]:
    """(translation key, value) pairs: Version, Build date (YYYY-MM-DD), Build time (HH:MM), Developer."""
    stamp = build_stamp()
    return [
        ("about_version", str(version)),
        ("about_build_date", stamp["build_date"]),
        ("about_build_time", stamp["build_time"]),
        ("about_developer", stamp["developer"]),
    ]
