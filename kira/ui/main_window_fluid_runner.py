from __future__ import annotations

from kira.ui.main_window_fluid_controller import attach_main_window_fluid
from kira.ui.main_window_fluid_mixin import MainWindowFluidMixin
from kira.ui.window_fluid_guard import wire_main_window_fluid


class MainWindowFluidRunner(MainWindowFluidMixin):
    """Runner applying direct fluid layout wiring to a main window instance."""

    def __init__(self, window) -> None:
        self.window = window
        wire_main_window_fluid(window)
        self.init_fluid_layout()
        attach_main_window_fluid(window)


def run_main_window_fluid_wiring(window) -> MainWindowFluidRunner:
    """Execute direct main window fluid wiring and return the runner."""
    return MainWindowFluidRunner(window)
