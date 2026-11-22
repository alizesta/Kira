"""Fail-closed permissions for Ai1 gameplay profiles."""
from __future__ import annotations

STORY_MODE = "story"
COMPETITIVE_SAFE_MODE = "competitive_safe"

_BASELINE_DENIED = {
    "overlay": False,
    "process_memory_read": False,
    "process_memory_write": False,
    "code_injection": False,
    "graphics_api_hooks": False,
    "game_file_modification": False,
    "driver_installation": False,
}


def normalize_game_mode_profile(profile: str | None) -> str:
    value = str(profile or "").strip().lower()
    return value if value in (STORY_MODE, COMPETITIVE_SAFE_MODE) else COMPETITIVE_SAFE_MODE


def game_mode_permissions(profile: str | None) -> dict[str, bool]:
    """Return explicit feature permissions for one profile."""
    normalized = normalize_game_mode_profile(profile)
    permissions = dict(_BASELINE_DENIED)
    permissions.update({
        "microphone_wake_word": True,
        "input_automation": normalized == STORY_MODE,
        # Screen observation is read-only and remains available in both profiles.
        # It is still gated by explicit Game Mode activation and foreground-game detection.
        "vision_capture": True,
        "game_audio_loopback": normalized == STORY_MODE,
        "automatic_game_audio_alerts": normalized == STORY_MODE,
    })
    return permissions


def tool_categories_allowed(profile: str | None, categories) -> bool:
    """Competitive Safe permits web research only; local-control/unknown tools fail closed."""
    if normalize_game_mode_profile(profile) == STORY_MODE:
        return True
    values = set(categories or ())
    return bool(values) and values.issubset({"web"})
