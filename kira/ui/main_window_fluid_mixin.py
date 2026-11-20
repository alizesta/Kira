from __future__ import annotations

from kira.ui.window_fluid_guard import wire_main_window_fluid


class MainWindowFluidMixin:
    """Mixin injecting direct wire_main_window_fluid calls into main window instances."""

    def init_fluid_layout(self) -> None:
        wire_main_window_fluid(self)
