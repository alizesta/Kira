from __future__ import annotations

from kira.ui.pages._all_pages_fluid_finalizers import (
    finalize_appearance_page,
    finalize_assistant_page,
    finalize_characters_page,
    finalize_help_page,
    finalize_preferences_page,
    finalize_skills_page,
    finalize_voice_page,
)
from kira.ui.pages._responsive_page_helper import normalize_page_widget


def apply_direct_page_fluid_calls(pages_map: dict) -> dict:
    """Invoke direct normalization and finalizer functions on page instances."""
    finalizers = {
        "appearance": finalize_appearance_page,
        "assistant": finalize_assistant_page,
        "characters": finalize_characters_page,
        "help": finalize_help_page,
        "preferences": finalize_preferences_page,
        "skills": finalize_skills_page,
        "voice": finalize_voice_page,
    }
    result = {}
    for key, page in (pages_map or {}).items():
        if page is None:
            continue
        normalize_page_widget(page)
        fin = finalizers.get(str(key).lower())
        if fin is not None:
            fin(page)
        result[key] = page
    return result
