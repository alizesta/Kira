from __future__ import annotations

from PySide6.QtWidgets import QScrollArea, QWidget

from kira.ui.responsive_layout import configure_fluid_layout_on_widget


def normalize_page_widget(page_widget: QWidget):
    """Apply fluid sizing in place without wrapping an existing page in another scroll area."""
    if page_widget is None:
        return None
    if isinstance(page_widget, QScrollArea):
        page_widget.setWidgetResizable(True)
    configure_fluid_layout_on_widget(page_widget)
    content = page_widget.widget() if isinstance(page_widget, QScrollArea) else None
    if content is not None:
        configure_fluid_layout_on_widget(content)
    return page_widget


def wire_pages_fluid(pages: dict | list | tuple | None) -> dict:
    """Normalize a page map/collection in place and return its normalized mapping."""
    if not pages:
        return {}
    if isinstance(pages, dict):
        return {key: normalize_page_widget(value) for key, value in pages.items() if value is not None}
    return {index: normalize_page_widget(page) for index, page in enumerate(pages) if page is not None}
