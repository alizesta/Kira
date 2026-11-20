from __future__ import annotations

from kira.ui.pages._pages_finalizer_entry import apply_all_page_finalizers


def run_direct_page_finalizers(pages: dict | None = None) -> dict:
    """Directly invoke apply_all_page_finalizers across all page widgets."""
    return apply_all_page_finalizers(pages)
