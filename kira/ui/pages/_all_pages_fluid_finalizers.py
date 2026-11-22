from __future__ import annotations

from kira.ui.pages._responsive_page_helper import normalize_page_widget
from kira.ui.pages.audio_card_simplify import simplify_audio_cards


def finalize_appearance_page(page):
    return normalize_page_widget(page)


def finalize_assistant_page(page):
    return normalize_page_widget(page)


def finalize_characters_page(page):
    return normalize_page_widget(page)


def finalize_help_page(page):
    return normalize_page_widget(page)


def finalize_preferences_page(page):
    return normalize_page_widget(page)


def finalize_skills_page(page):
    return normalize_page_widget(page)


def finalize_voice_page(page):
    simplify_audio_cards(page)
    return normalize_page_widget(page)
