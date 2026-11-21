from __future__ import annotations

from kira.ui.window_fluid_guard import wire_main_window_fluid


def run_main_window_fluid_wiring(window):
    """Apply main-window fluid sizing once without recursive controller attachment."""
    wire_main_window_fluid(window)
    return window
