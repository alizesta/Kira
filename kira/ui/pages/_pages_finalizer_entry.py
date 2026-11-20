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


def apply_all_page_finalizers(pages: dict | None = None) -> dict:
    """Invoke direct per-page finalizers for every settings/feature page."""
    registry = {
        "appearance": finalize_appearance_page,
        "assistant": finalize_assistant_page,
        "characters": finalize_characters_page,
        "help": finalize_help_page,
        "preferences": finalize_preferences_page,
        "skills": finalize_skills_page,
        "voice": finalize_voice_page,
    }
    if not pages:
        return {}
    return {
        key: (registry[str(key).lower()](widget) if str(key).lower() in registry else widget)
        for key, widget in pages.items()
        if widget is not None
    }
