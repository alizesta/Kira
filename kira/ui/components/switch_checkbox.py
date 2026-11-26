"""A QCheckBox that looks like the on/off switch every settings screen uses (Jakob's law).

Behaviour, API and signals are exactly QCheckBox's (isChecked / setChecked / toggled / text), only the indicator is a switch.
The knob slides and the track colour blends over ANIMATION_MS when the user toggles a visible switch; a switch that is
hidden (or being built) jumps straight to its state, so opening a settings page never plays a wave of animations."""
from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QCheckBox, QStyle, QStyleOptionButton, QStylePainter

ON, OFF, KNOB = QColor("#3ddc97"), QColor("#6b6f7b"), QColor("#ffffff")
ANIMATION_MS = 160


def _blend(start: QColor, end: QColor, t: float) -> QColor:
    """Linear colour mix; t=0 gives `start`, t=1 gives `end`."""
    return QColor(
        round(start.red() + (end.red() - start.red()) * t),
        round(start.green() + (end.green() - start.green()) * t),
        round(start.blue() + (end.blue() - start.blue()) * t),
    )


class SwitchCheckBox(QCheckBox):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("QCheckBox::indicator { width: 34px; height: 18px; }")    # reserves the room the switch is drawn in
        self._progress = 1.0 if self.isChecked() else 0.0
        # One animation per switch, reused: a new toggle restarts it instead of stacking a second one.
        self._animation = QPropertyAnimation(self, b"progress", self)
        self._animation.setDuration(ANIMATION_MS)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._on_toggled)

    def _get_progress(self) -> float:
        return self._progress

    def _set_progress(self, value: float) -> None:
        value = max(0.0, min(1.0, float(value)))
        if value != self._progress:
            self._progress = value
            self.update()

    progress = Property(float, _get_progress, _set_progress)

    def _target(self) -> float:
        return 1.0 if self.isChecked() else 0.0

    def _on_toggled(self, _checked: bool) -> None:
        self._animation.stop()
        if not self.isVisible():
            self._set_progress(self._target())
            return
        self._animation.setStartValue(self._progress)
        self._animation.setEndValue(self._target())
        self._animation.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._animation.state() != QPropertyAnimation.State.Running:
            self._set_progress(self._target())        # a switch shown for the first time never starts mid-way

    def paintEvent(self, _event) -> None:
        painter = QStylePainter(self)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        indicator = self.style().subElementRect(QStyle.SE_CheckBoxIndicator, option, self)
        option.rect = self.style().subElementRect(QStyle.SE_CheckBoxContents, option, self)
        painter.drawControl(QStyle.CE_CheckBoxLabel, option)
        painter.setRenderHint(QPainter.Antialiasing)
        track = QRectF(indicator).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setOpacity(1.0 if self.isEnabled() else 0.45)
        painter.setPen(Qt.NoPen)
        painter.setBrush(_blend(OFF, ON, self._progress))
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        d = track.height() - 6
        left, right = track.left() + 3, track.right() - d - 3
        x = left + (right - left) * self._progress
        painter.setBrush(KNOB)
        painter.drawEllipse(QRectF(x, track.top() + 3, d, d))
        if self.hasFocus():
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QColor("#ffffff"))
            painter.drawRoundedRect(track.adjusted(-1, -1, 1, 1), track.height() / 2, track.height() / 2)
