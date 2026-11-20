from __future__ import annotations

from kira.ui.pages._pages_finalizer_entry import apply_all_page_finalizers


def finalize_existing_page_targets(page_map: dict | None = None) -> dict:
    """Directly invoke apply_all_page_finalizers on page widgets."""
    return apply_all_page_finalizers(page_map)
