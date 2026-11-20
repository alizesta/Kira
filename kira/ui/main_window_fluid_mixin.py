from __future__ import annotations

from kira.ui.pages._responsive_page_helper import normalize_page_widget
from kira.ui.window_fluid_guard import wire_main_window_fluid


class MainWindowFluidMixin:
    """Mixin injecting direct wire_main_window_fluid calls into main window instances."""

    def init_fluid_layout(self) -> None:
        wire_main_window_fluid(self)
        if hasattr(self, "pages") and isinstance(self.pages, dict):
            for key, page in list(self.pages.items()):
                if page is not None:
                    self.pages[key] = normalize_page_widget(page)
