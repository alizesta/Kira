from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QGroupBox, QLineEdit, QPlainTextEdit, QScrollArea, QSpinBox, QTextEdit, QWidget

from kira.ui.responsive_layout import configure_fluid_layout_on_widget


def normalize_page_widget(page_widget: QWidget):
    """Apply fluid sizing in place without wrapping an existing page in another scroll area."""
    if page_widget is None:
        return None
    if isinstance(page_widget, QScrollArea):
        page_widget.setWidgetResizable(True)
        page_widget.setAlignment(Qt.AlignHCenter)
    configure_fluid_layout_on_widget(page_widget)
    content = page_widget.widget() if isinstance(page_widget, QScrollArea) else page_widget
    if content is not None:
        configure_fluid_layout_on_widget(content)
        if isinstance(page_widget, QScrollArea):
            content.setMaximumWidth(1180)
        for group in content.findChildren(QGroupBox):
            group.setMaximumWidth(1120)
        for field_type in (QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox):
            for field in content.findChildren(field_type):
                field.setMaximumWidth(520)
        for field_type in (QTextEdit, QPlainTextEdit):
            for field in content.findChildren(field_type):
                field.setMaximumWidth(760)
    return page_widget


def wire_pages_fluid(pages: dict | list | tuple | None) -> dict:
    """Normalize a page map/collection in place and return its normalized mapping."""
    if not pages:
        return {}
    if isinstance(pages, dict):
        return {key: normalize_page_widget(value) for key, value in pages.items() if value is not None}
    return {index: normalize_page_widget(page) for index, page in enumerate(pages) if page is not None}
