from __future__ import annotations

from kira.ui.pages._responsive_page_helper import normalize_page_widget


def bind_page_direct(page):
    """Direct binding of fluid normalization onto a page widget."""
    return normalize_page_widget(page)
