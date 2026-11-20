from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QLayout,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


def apply_fluid_policy(widget: QWidget, min_w: int = 0, min_h: int = 0, expand_h: bool = False) -> None:
    """Apply non-locking minimum bounds and flexible size policies."""
    h_policy = QSizePolicy.Policy.Expanding if expand_h else QSizePolicy.Policy.Minimum
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, h_policy)
    if min_w > 0 or min_h > 0:
        widget.setMinimumSize(min_w, min_h)


def wrap_in_responsive_scroll(content: QWidget, parent: QWidget | None = None) -> QScrollArea:
    """Wrap a settings/content widget in a resizable scroll area that never clips content."""
    content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    scroll = QScrollArea(parent)
    scroll.setObjectName("responsiveScrollArea")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    scroll.setWidget(content)
    return scroll


def configure_fluid_layout(layout: QLayout, margins: tuple[int, int, int, int] = (12, 10, 12, 12), spacing: int = 10) -> None:
    """Configure layout margins/spacing and constraint behavior for safe window resizing."""
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)


def make_page_container(content: QWidget, parent: QWidget | None = None) -> QScrollArea:
    """Standardize any settings/feature page into a fluid, non-clipping scrollable container."""
    configure_fluid_layout_on_widget(content)
    return wrap_in_responsive_scroll(content, parent=parent)


def configure_fluid_layout_on_widget(widget: QWidget) -> None:
    """Ensure top-level layout on a widget uses fluid margins/spacing and never clips children."""
    layout = widget.layout()
    if layout is not None:
        configure_fluid_layout(layout)
    apply_fluid_policy(widget, min_w=0, min_h=0, expand_h=False)


class FluidPageContainer(QWidget):
    """Standardized Jakob-familiar page container with fluid resizing."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.body_layout = QVBoxLayout(self)
        configure_fluid_layout(self.body_layout)
