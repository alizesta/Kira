from __future__ import annotations

from kira.ui.pages._pages_finalizer_entry import apply_all_page_finalizers


def finalize_pages_bundle(pages: dict | None = None) -> dict:
    """Directly invoke apply_all_page_finalizers for page bundles."""
    return apply_all_page_finalizers(pages)
