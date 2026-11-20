from __future__ import annotations

from PyQt6.QtWidgets import (
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


def wrap_in_responsive_scroll(content: QWidget, parent: QWidget | None = None) -> QScrollArea:
    """Wrap a settings/content widget in a resizable scroll area that never clips content."""
    content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    scroll = QScrollArea(parent)
    scroll.setObjectName("responsiveScrollArea")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded if False else scroll.horizontalScrollBarPolicy())
    scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    scroll.setWidget(content)
    return scroll


class FluidPageContainer(QWidget):
    """Standardized fluid page container following familiar top-to-bottom rhythm."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.body_layout = QVBoxLayout(self)
        self.body_layout.setContentsMargins(12, 10, 12, 12)
        self.body_layout.setSpacing(10)
