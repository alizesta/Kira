from __future__ import annotations

from kira.ui.main_window_fluid_mixin import MainWindowFluidMixin
from kira.ui.window_fluid_guard import wire_main_window_fluid


def apply_main_window_fluid_layout(window) -> None:
    """Apply fluid layout rules directly to the main window instance."""
    if isinstance(window, MainWindowFluidMixin):
        window.init_fluid_layout()
    else:
        wire_main_window_fluid(window)
