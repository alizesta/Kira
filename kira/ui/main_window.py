from __future__ import annotations

from kira.ui.main_window_fluid_entry import enable_main_window_fluid
from kira.ui.pages._pages_finalizer_entry import apply_all_page_finalizers


class KiraMainWindow:
    """Responsive main window wiring fluid layout and all page finalizers."""

    def __init__(self, pages: dict | None = None) -> None:
        self.pages = pages or {}
        enable_main_window_fluid(self)
        apply_all_page_finalizers(self.pages)
