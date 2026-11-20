from __future__ import annotations

from kira.ui.pages._pages_finalizer_entry import apply_all_page_finalizers


def apply_direct_pages_finalizers(pages: dict | None = None) -> dict:
    """Apply apply_all_page_finalizers directly to page widgets."""
    return apply_all_page_finalizers(pages)
