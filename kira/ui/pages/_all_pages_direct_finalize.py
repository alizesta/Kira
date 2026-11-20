from __future__ import annotations

from kira.ui.pages._pages_finalizer_entry import apply_all_page_finalizers


def finalize_all_pages_direct(pages: dict | None = None) -> dict:
    """Directly execute apply_all_page_finalizers on all registered pages."""
    return apply_all_page_finalizers(pages)
