"""Reusable desktop UI patterns for progressive disclosure and connected flows.

These widgets are presentation-only. They do not own application state or
perform navigation, persistence, or other side effects.
"""
from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class ProgressiveDisclosure(QWidget):
    """A compact, accessible toggle for genuinely secondary controls."""

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.toggle = QToolButton(self)
        self.toggle.setText(str(label))
        self.toggle.setCheckable(True)
        self.toggle.setChecked(False)
        self.toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.RightArrow)
        self.content = QWidget(self)
        self.content.setVisible(False)
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(12, 4, 0, 4)
        self.content_layout.setSpacing(8)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.toggle, 0, Qt.AlignLeft)
        layout.addWidget(self.content)
        self.toggle.toggled.connect(self._set_expanded)

    def addWidget(self, widget: QWidget) -> None:
        self.content_layout.addWidget(widget)

    def _set_expanded(self, expanded: bool) -> None:
        self.content.setVisible(expanded)
        self.toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.toggle.setAccessibleName(self.toggle.text())
        self.toggle.setAccessibleDescription(
            "بستن گزینه‌های پیشرفته" if expanded else "نمایش گزینه‌های پیشرفته"
        )


class ConnectedSteps(QWidget):
    """A compact connected sequence with explicit current/completed states."""

    def __init__(
        self,
        labels: Iterable[str],
        current_step: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._labels = tuple(str(label) for label in labels)
        if not self._labels:
            raise ValueError("ConnectedSteps requires at least one label")
        if not 0 <= current_step < len(self._labels):
            raise ValueError("current_step must identify an existing step")

        self._items: list[tuple[QLabel, QLabel]] = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        for index, label in enumerate(self._labels):
            marker = QLabel("✓" if index < current_step else str(index + 1), self)
            marker.setAlignment(Qt.AlignCenter)
            marker.setFixedSize(26, 26)
            marker.setProperty("stepState", self._state(index, current_step))
            title = QLabel(label, self)
            title.setWordWrap(True)
            title.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
            title.setProperty("stepState", self._state(index, current_step))
            item = QWidget(self)
            item_layout = QVBoxLayout(item)
            item_layout.setContentsMargins(0, 0, 0, 0)
            item_layout.setSpacing(4)
            item_layout.addWidget(marker, 0, Qt.AlignHCenter)
            item_layout.addWidget(title)
            layout.addWidget(item, 1)
            self._items.append((marker, title))
            if index < len(self._labels) - 1:
                connector = QFrame(self)
                connector.setFrameShape(QFrame.HLine)
                connector.setObjectName("stepConnector")
                layout.addWidget(connector, 0)
        self.set_current_step(current_step)

    @staticmethod
    def _state(index: int, current_step: int) -> str:
        if index < current_step:
            return "completed"
        if index == current_step:
            return "current"
        return "upcoming"

    def set_current_step(self, current_step: int) -> None:
        if not 0 <= current_step < len(self._labels):
            raise ValueError("current_step must identify an existing step")
        for index, (marker, title) in enumerate(self._items):
            state = self._state(index, current_step)
            marker.setText("✓" if index < current_step else str(index + 1))
            for widget in (marker, title):
                widget.setProperty("stepState", state)
                widget.style().unpolish(widget)
                widget.style().polish(widget)
