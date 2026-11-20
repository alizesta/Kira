from __future__ import annotations

from kira.ui.main_window_fluid_hook import apply_main_window_fluid_layout
from kira.ui.main_window_fluid_mixin import MainWindowFluidMixin
from kira.ui.window_fluid_guard import wire_main_window_fluid


class MainWindowFluidController(MainWindowFluidMixin):
    """Direct fluid layout entrypoint for Kira main window instances."""

    def __init__(self, window) -> None:
        self.window = window
        wire_main_window_fluid(window)
        self.init_fluid_layout()

    def apply(self) -> None:
        apply_main_window_fluid_layout(self.window)
        wire_main_window_fluid(self.window)
        self.init_fluid_layout()


def attach_main_window_fluid(window) -> MainWindowFluidController:
    """Attach and return the fluid layout controller for a main window."""
    controller = MainWindowFluidController(window)
    controller.apply()
    return controller
