from __future__ import annotations

from kira.ui.responsive_layout import configure_fluid_layout_on_widget, wrap_in_responsive_scroll


def normalize_page_widget(page_widget):
    """Apply Jakob-familiar fluid sizing and safe scroll containment to a page widget."""
    configure_fluid_layout_on_widget(page_widget)
    return wrap_in_responsive_scroll(page_widget, parent=page_widget.parent())


def wire_pages_fluid(pages: dict | list | tuple | None) -> dict:
    """Wire all UI pages in a page map/collection to fluid non-clipping containers."""
    if not pages:
        return {}
    if isinstance(pages, dict):
        return {key: normalize_page_widget(val) for key, val in pages.items() if val is not None}
    return {idx: normalize_page_widget(page) for idx, page in enumerate(pages) if page is not None}
