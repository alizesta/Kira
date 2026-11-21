"""Compact live activity panel for Kode's user-visible work stages."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QListWidget, QToolButton, QVBoxLayout


class KodeActivityPanel(QFrame):
    """Show concise, factual progress without exposing model reasoning."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("kodeActivity")
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "QFrame#kodeActivity { background: rgba(72, 57, 112, 28); "
            "border: 1px solid rgba(143, 107, 255, 90); border-radius: 10px; }"
            "QLabel#kodeActivityTitle { color: #cfc4ff; font-weight: 600; }"
            "QLabel#kodeActivityStatus { color: palette(text); }"
            "QListWidget#kodeActivitySteps { border: 0; background: transparent; "
            "padding: 0 4px; color: palette(text); }"
            "QToolButton#kodeActivityToggle { border: 0; color: #cfc4ff; padding: 2px 6px; }"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 6, 10, 6)
        outer.setSpacing(3)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        self.title = QLabel("فعالیت کیرا")
        self.title.setObjectName("kodeActivityTitle")
        self.status = QLabel("در حال آماده‌سازی…")
        self.status.setObjectName("kodeActivityStatus")
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.toggle = QToolButton()
        self.toggle.setObjectName("kodeActivityToggle")
        self.toggle.setText("جزئیات")
        self.toggle.setCheckable(True)
        self.toggle.setChecked(False)
        self.toggle.toggled.connect(self._toggle_details)
        header.addWidget(self.title)
        header.addWidget(self.status, 1)
        header.addWidget(self.toggle)
        outer.addLayout(header)

        self.steps = QListWidget()
        self.steps.setObjectName("kodeActivitySteps")
        self.steps.setMaximumHeight(82)
        self.steps.setFocusPolicy(Qt.NoFocus)
        self.steps.hide()
        outer.addWidget(self.steps)
        self._generation = 0
        self._active = False
        self.hide()

    def _toggle_details(self, expanded: bool) -> None:
        self.steps.setVisible(bool(expanded and self.steps.count()))

    def start(self, status: str) -> None:
        self._generation += 1
        self._active = True
        self.steps.clear()
        self.toggle.setChecked(False)
        self._append(status)
        self.status.setText(status)
        self.show()

    def update(self, status: str) -> None:
        status = str(status or "").strip()
        if not status:
            return
        if not self._active:
            self.start(status)
            return
        self.status.setText(status)
        self._append(status)

    def step(self, description: str) -> None:
        description = str(description or "").strip()
        if not description:
            return
        if not self._active:
            self.start(description)
            return
        self.status.setText(description)
        self._append(description)

    def _append(self, description: str) -> None:
        description = str(description or "").strip()
        if not description:
            return
        last = self.steps.item(self.steps.count() - 1)
        if last is not None and last.text() == description:
            return
        self.steps.addItem("• " + description)
        while self.steps.count() > 5:
            self.steps.takeItem(0)
        if self.toggle.isChecked():
            self.steps.setVisible(True)

    def complete(self, status: str = "انجام شد") -> None:
        self.status.setText(status)
        self._append(status)
        generation = self._generation
        def hide_if_current():
            if generation == self._generation:
                self._active = False
                self.hide()
        QTimer.singleShot(6000, hide_if_current)

    def fail(self, status: str = "با خطا متوقف شد") -> None:
        self.status.setText(status)
        self._append(status)
        generation = self._generation
        def hide_if_current():
            if generation == self._generation:
                self._active = False
                self.hide()
        QTimer.singleShot(10000, hide_if_current)

    def reset(self) -> None:
        self._generation += 1
        self._active = False
        self.steps.clear()
        self.status.clear()
        self.hide()
