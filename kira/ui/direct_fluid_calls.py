from __future__ import annotations

from kira.ui.main_window_fluid_entry import enable_main_window_fluid
from kira.ui.pages._pages_finalizer_entry import apply_all_page_finalizers


def wire_direct_ui_fluid(window, pages: dict | None = None) -> dict | None:
    """Directly run enable_main_window_fluid and apply_all_page_finalizers."""
    enable_main_window_fluid(window)
    if pages is not None:
        return apply_all_page_finalizers(pages)
    return None
