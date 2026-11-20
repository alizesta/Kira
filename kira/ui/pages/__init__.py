from __future__ import annotations

from kira.ui.pages._responsive_page_helper import normalize_page_widget

from .appearance_page import AppearancePage
from .assistant_page import AssistantPage
from .characters_page import CharactersPage
from .help_page import HelpPage
from .preferences_page import PreferencesPage
from .skills_page import SkillsPage
from .voice_page import VoicePage


def normalize_all_pages(pages_by_key: dict) -> dict:
    """Inject direct normalize_page_widget calls across all registered settings/feature pages."""
    return {key: normalize_page_widget(widget) for key, widget in pages_by_key.items() if widget is not None}


__all__ = [
    "AppearancePage",
    "AssistantPage",
    "CharactersPage",
    "HelpPage",
    "PreferencesPage",
    "SkillsPage",
    "VoicePage",
    "normalize_all_pages",
]
