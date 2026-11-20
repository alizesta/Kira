from __future__ import annotations

from kira.ui.pages._responsive_page_helper import normalize_page_widget, wire_pages_fluid
from kira.ui.window_fluid_guard import wire_main_window_fluid


def attach_fluid_ui(window, pages=None):
    """Attach main window fluid sizing and normalize settings pages on demand."""
    wire_main_window_fluid(window)
    if pages is not None:
        return wire_pages_fluid(pages)
    return None


def finalize_page_fluid(page_widget):
    """Apply responsive fluid container normalization to an individual UI page."""
    return normalize_page_widget(page_widget)
