from __future__ import annotations

from kira.ui.main_window_fluid_runner import run_main_window_fluid_wiring


def enable_main_window_fluid(window) -> None:
    """Apply Jakob-familiar fluid layout rules directly to Kira's main window."""
    run_main_window_fluid_wiring(window)
