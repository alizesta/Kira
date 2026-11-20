"""A QCheckBox that looks like the on/off switch every settings screen uses (Jakob's law).

Behaviour, API and signals are exactly QCheckBox's (isChecked / setChecked / toggled / text), only the indicator is a switch."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QCheckBox, QStyle, QStyleOptionButton, QStylePainter

ON, OFF, KNOB = QColor("#3ddc97"), QColor("#6b6f7b"), QColor("#ffffff")


class SwitchCheckBox(QCheckBox):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("QCheckBox::indicator { width: 34px; height: 18px; }")    # reserves the room the switch is drawn in

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
        painter.setBrush(ON if self.isChecked() else OFF)
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        d = track.height() - 6
        x = track.right() - d - 3 if self.isChecked() else track.left() + 3
        painter.setBrush(KNOB)
        painter.drawEllipse(QRectF(x, track.top() + 3, d, d))
        if self.hasFocus():
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QColor("#ffffff"))
            painter.drawRoundedRect(track.adjusted(-1, -1, 1, 1), track.height() / 2, track.height() / 2)
