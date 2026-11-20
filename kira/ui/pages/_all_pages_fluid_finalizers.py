from __future__ import annotations

from kira.ui.pages._page_fluid_hook import apply_page_fluid_normalization
from kira.ui.pages._responsive_page_helper import normalize_page_widget


def finalize_appearance_page(page):
    apply_page_fluid_normalization(page)
    return normalize_page_widget(page)


def finalize_assistant_page(page):
    apply_page_fluid_normalization(page)
    return normalize_page_widget(page)


def finalize_characters_page(page):
    apply_page_fluid_normalization(page)
    return normalize_page_widget(page)


def finalize_help_page(page):
    apply_page_fluid_normalization(page)
    return normalize_page_widget(page)


def finalize_preferences_page(page):
    apply_page_fluid_normalization(page)
    return normalize_page_widget(page)


def finalize_skills_page(page):
    apply_page_fluid_normalization(page)
    return normalize_page_widget(page)


def finalize_voice_page(page):
    apply_page_fluid_normalization(page)
    return normalize_page_widget(page)
