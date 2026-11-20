from __future__ import annotations

from kira.ui.pages._responsive_page_helper import normalize_page_widget


def apply_page_fluid_normalization(page):
    """Apply normalize_page_widget directly to a settings or feature page instance."""
    return normalize_page_widget(page)
