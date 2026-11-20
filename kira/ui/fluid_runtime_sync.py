from __future__ import annotations

from kira.ui.main_window_fluid_entry import enable_main_window_fluid
from kira.ui.pages._pages_finalizer_entry import apply_all_page_finalizers


def sync_direct_ui_runtime(window, pages: dict | None = None) -> dict | None:
    """Direct runtime helper calling enable_main_window_fluid and apply_all_page_finalizers."""
    enable_main_window_fluid(window)
    if pages is not None:
        return apply_all_page_finalizers(pages)
    return None
