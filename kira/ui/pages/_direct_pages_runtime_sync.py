from __future__ import annotations

from kira.ui.pages._pages_finalizer_entry import apply_all_page_finalizers


def sync_direct_pages_runtime(pages: dict | None = None) -> dict:
    """Direct runtime helper calling apply_all_page_finalizers across all pages."""
    return apply_all_page_finalizers(pages)
