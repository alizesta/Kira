from __future__ import annotations

from kira.ui.fluid_wiring import attach_fluid_ui


def bind_main_window_direct(window, pages: dict | None = None):
    """Direct binding of main window fluid UI and registered pages."""
    return attach_fluid_ui(window, pages=pages)
