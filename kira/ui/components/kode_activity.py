"""Live progress checklist for Kira's visible work stages.

Shows real, factual stages only (never model reasoning): each stage is a
checklist row that is active while it runs and turns into a check mark when it
finishes. A slim neon progress bar summarises the run.
"""
from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

PENDING, ACTIVE, DONE, FAILED, STOPPED = "pending", "active", "done", "failed", "stopped"

_VIOLET = QColor(143, 107, 255)
_CYAN = QColor(82, 229, 255)
_GREEN = QColor(94, 242, 176)
_RED = QColor(255, 107, 138)
_AMBER = QColor(255, 193, 77)
_MAX_ROWS = 8
_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _fa(number: int) -> str:
    return str(number).translate(_PERSIAN_DIGITS)


def _alpha(color: QColor, alpha: int) -> QColor:
    out = QColor(color)
    out.setAlpha(alpha)
    return out


class _StateIcon(QWidget):
    """Painted status glyph (ring / spinning arc / check / cross / pause) - no font dependency."""

    def __init__(self, size: int = 18, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.state = PENDING
        self.angle = 0

    def set_state(self, state: str) -> None:
        self.state = state
        self.update()

    def tick(self, angle: int) -> None:
        self.angle = angle
        if self.state == ACTIVE:
            self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = min(self.width(), self.height())
        r = QRectF(2.0, 2.0, s - 4.0, s - 4.0)
        c = r.center()
        if self.state == ACTIVE:
            p.setPen(QPen(_alpha(_VIOLET, 60), 1.6))
            p.drawEllipse(r)
            glow = QPen(_alpha(_CYAN, 55), 4.6)
            glow.setCapStyle(Qt.RoundCap)
            p.setPen(glow)
            p.drawArc(r, -self.angle * 16, 110 * 16)
            arc = QPen(_CYAN, 2.2)
            arc.setCapStyle(Qt.RoundCap)
            p.setPen(arc)
            p.drawArc(r, -self.angle * 16, 110 * 16)
        elif self.state == DONE:
            p.setPen(QPen(_GREEN, 1.4))
            p.setBrush(_alpha(_GREEN, 42))
            p.drawEllipse(r)
            tick = QPen(_GREEN, 1.9)
            tick.setCapStyle(Qt.RoundCap)
            tick.setJoinStyle(Qt.RoundJoin)
            p.setPen(tick)
            p.drawPolyline([QPointF(c.x() - 3.4, c.y() + 0.2), QPointF(c.x() - 0.9, c.y() + 2.8),
                            QPointF(c.x() + 3.6, c.y() - 2.6)])
        elif self.state == FAILED:
            p.setPen(QPen(_RED, 1.4))
            p.setBrush(_alpha(_RED, 42))
            p.drawEllipse(r)
            cross = QPen(_RED, 1.9)
            cross.setCapStyle(Qt.RoundCap)
            p.setPen(cross)
            p.drawLine(QPointF(c.x() - 2.8, c.y() - 2.8), QPointF(c.x() + 2.8, c.y() + 2.8))
            p.drawLine(QPointF(c.x() - 2.8, c.y() + 2.8), QPointF(c.x() + 2.8, c.y() - 2.8))
        elif self.state == STOPPED:
            p.setPen(QPen(_AMBER, 1.4))
            p.setBrush(_alpha(_AMBER, 42))
            p.drawEllipse(r)
            bar = QPen(_AMBER, 1.9)
            bar.setCapStyle(Qt.RoundCap)
            p.setPen(bar)
            p.drawLine(QPointF(c.x() - 1.7, c.y() - 2.6), QPointF(c.x() - 1.7, c.y() + 2.6))
            p.drawLine(QPointF(c.x() + 1.7, c.y() - 2.6), QPointF(c.x() + 1.7, c.y() + 2.6))
        else:  # pending
            p.setPen(QPen(QColor(255, 255, 255, 80), 1.4))
            p.drawEllipse(r)
        p.end()


class _StepRow(QWidget):
    _TEXT = {
        PENDING: "color: #8c90a8;",
        ACTIVE: "color: #f1eeff; font-weight: 600;",
        DONE: "color: #a3a8c0;",
        FAILED: "color: #ff9fb3;",
        STOPPED: "color: #ffd78a;",
    }

    def __init__(self, text: str, state: str, key: str | None, parent=None):
        super().__init__(parent)
        self.key = key
        self.text = text
        self.state = state
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 1, 0, 1)
        lay.setSpacing(9)
        self.icon = _StateIcon(18)
        self.label = QLabel(text)
        self.label.setStyleSheet("background: transparent;")
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.icon, 0, Qt.AlignTop)
        lay.addWidget(self.label, 1)
        self.set_state(state)

    def set_state(self, state: str, text: str | None = None) -> None:
        self.state = state
        if text is not None:
            self.text = text
            self.label.setText(text)
        self.icon.set_state(state)
        self.label.setStyleSheet("background: transparent; " + self._TEXT.get(state, ""))


class _ProgressBar(QWidget):
    """Slim neon bar; animates smoothly between values."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(4)
        self._value = 0.0
        self._failed = False
        self._anim = QPropertyAnimation(self, b"value", self)
        self._anim.setDuration(320)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def get_value(self) -> float:
        return self._value

    def set_value(self, value: float) -> None:
        self._value = max(0.0, min(1.0, float(value)))
        self.update()

    value = Property(float, get_value, set_value)

    def go_to(self, value: float, failed: bool = False) -> None:
        self._failed = failed
        self._anim.stop()
        self._anim.setStartValue(self._value)
        self._anim.setEndValue(max(0.0, min(1.0, float(value))))
        self._anim.start()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = float(self.width()), float(self.height())
        radius = h / 2.0
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 22))
        p.drawRoundedRect(QRectF(0, 0, w, h), radius, radius)
        fill = max(w * self._value, h) if self._value > 0 else 0.0
        if fill <= 0:
            p.end()
            return
        rtl = self.layoutDirection() == Qt.RightToLeft
        x0 = w - fill if rtl else 0.0
        grad = QLinearGradient(x0, 0, x0 + fill, 0)
        if self._failed:
            grad.setColorAt(0.0, _RED)
            grad.setColorAt(1.0, _AMBER)
        else:
            first, second = (_CYAN, _VIOLET) if rtl else (_VIOLET, _CYAN)
            grad.setColorAt(0.0, first)
            grad.setColorAt(1.0, second)
        p.setBrush(grad)
        p.drawRoundedRect(QRectF(x0, 0, fill, h), radius, radius)
        p.end()


class KodeActivityPanel(QFrame):
    """Compact progress checklist: header + neon progress bar + collapsible step list."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("kodeActivity")
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet(
            "QFrame#kodeActivity { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, "
            "stop:0 rgba(46, 36, 92, 150), stop:1 rgba(20, 30, 62, 150)); "
            "border: 1px solid rgba(143, 107, 255, 120); border-radius: 12px; }"
            "QWidget#kodeActivityBody { background: transparent; }"
            "QLabel#kodeActivityStatus { background: transparent; color: #ece8ff; font-weight: 600; }"
            "QLabel#kodeActivityCount { color: #8fe9ff; font-size: 9pt; padding: 1px 8px; "
            "background: rgba(82, 229, 255, 26); border-radius: 8px; }"
            "QToolButton#kodeActivityToggle { background: transparent; border: 0; color: #cfc4ff; padding: 2px 6px; font-size: 10pt; }"
            "QToolButton#kodeActivityToggle:hover { color: #ffffff; }"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 9, 12, 10)
        outer.setSpacing(7)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(9)
        self.header_icon = _StateIcon(20)
        self.status = QLabel("در حال آماده‌سازی…")
        self.status.setObjectName("kodeActivityStatus")
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.count = QLabel("")
        self.count.setObjectName("kodeActivityCount")
        self.count.hide()
        self.toggle = QToolButton()
        self.toggle.setObjectName("kodeActivityToggle")
        self.toggle.setText("▾")
        self.toggle.setToolTip("نمایش / پنهان‌کردن مراحل")
        self.toggle.setCursor(Qt.PointingHandCursor)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(True)
        self.toggle.toggled.connect(self._on_toggled)
        header.addWidget(self.header_icon)
        header.addWidget(self.status, 1)
        header.addWidget(self.count)
        header.addWidget(self.toggle)
        outer.addLayout(header)

        self.bar = _ProgressBar()
        outer.addWidget(self.bar)

        self.body = QWidget()
        self.body.setObjectName("kodeActivityBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(2, 2, 2, 0)
        self.body_layout.setSpacing(1)
        outer.addWidget(self.body)

        self._rows: list[_StepRow] = []
        self._active = False
        self._user_toggled = False
        self._angle = 0
        self._spin = QTimer(self)
        self._spin.setInterval(33)
        self._spin.timeout.connect(self._tick)
        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.timeout.connect(self._auto_collapse)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide_completed)
        self.hide()

    # ------------------------------------------------------------------ view helpers
    def items(self) -> list[tuple[str, str]]:
        """(text, state) of every visible checklist row, oldest first."""
        return [(row.text, row.state) for row in self._rows]

    def _on_toggled(self, expanded: bool) -> None:
        self._user_toggled = True
        self.toggle.setText("▾" if expanded else "▴")
        self.body.setVisible(bool(expanded and self._rows))

    def _tick(self) -> None:
        self._angle = (self._angle + 11) % 360
        self.header_icon.tick(self._angle)
        for row in self._rows:
            row.icon.tick(self._angle)

    def _auto_collapse(self) -> None:
        if not self._user_toggled:
            self.toggle.blockSignals(True)
            self.toggle.setChecked(False)
            self.toggle.setText("▴")
            self.toggle.blockSignals(False)
            self.body.hide()

    def _hide_completed(self) -> None:
        self._active = False
        self._spin.stop()
        self.hide()

    def _stop_timers(self) -> None:
        self._collapse_timer.stop()
        self._hide_timer.stop()

    def _refresh(self, header_state: str | None = None) -> None:
        total = len(self._rows)
        done = sum(1 for r in self._rows if r.state == DONE)
        running = any(r.state == ACTIVE for r in self._rows)
        if header_state is None:
            header_state = ACTIVE if running else DONE
        self.header_icon.set_state(header_state)
        if total >= 2:
            self.count.setText(f"{_fa(done)} از {_fa(total)}")
            self.count.show()
        else:
            self.count.hide()
        if running:
            value = (done + 0.5) / (total + 1)       # never full while work is still going on
        elif header_state in (FAILED, STOPPED):
            value = max(done / max(total, 1), 0.08)
        else:
            value = 1.0
        self.bar.go_to(value, failed=header_state == FAILED)
        self.body.setVisible(bool(self.toggle.isChecked() and self._rows))

    def _add_row(self, text: str, state: str, key: str | None) -> _StepRow:
        row = _StepRow(text, state, key)
        self._rows.append(row)
        self.body_layout.addWidget(row)
        while len(self._rows) > _MAX_ROWS:
            old = self._rows.pop(0)
            self.body_layout.removeWidget(old)
            old.deleteLater()
        return row

    def _settle_active(self, state: str = DONE) -> None:
        for row in self._rows:
            if row.state == ACTIVE:
                row.set_state(state)

    def _clear_rows(self) -> None:
        for row in self._rows:
            self.body_layout.removeWidget(row)
            row.deleteLater()
        self._rows.clear()

    # ------------------------------------------------------------------ public API
    def start(self, status: str) -> None:
        status = str(status or "").strip() or "در حال آماده‌سازی…"
        self._stop_timers()
        self._clear_rows()
        self._active = True
        self._user_toggled = False
        self.toggle.blockSignals(True)
        self.toggle.setChecked(True)
        self.toggle.setText("▾")
        self.toggle.blockSignals(False)
        self.bar.set_value(0.0)
        self._add_row(status, ACTIVE, None)
        self.status.setText(status)
        self._refresh()
        self._spin.start()
        self.show()

    def ensure_running(self, status: str) -> None:
        """Make sure the checklist is visible while a request is in flight."""
        if not self._active:
            self.start(status)

    def begin(self, text: str, key: str | None = None) -> None:
        """Previous stage is finished; this one is now running."""
        text = str(text or "").strip()
        if not text:
            return
        if not self._active:
            self.start(text)
            if key is not None:
                self._rows[-1].key = key
            return
        last = self._rows[-1] if self._rows else None
        if last is not None and last.state == ACTIVE and last.text == text:
            return
        self._settle_active(DONE)
        self._add_row(text, ACTIVE, key)
        self.status.setText(text)
        self._refresh()

    def finish(self, key: str, text: str | None = None, state: str = DONE) -> None:
        """Resolve the running stage identified by `key` (adds a row if it was never shown)."""
        if not self._active:
            return
        target = next((r for r in reversed(self._rows) if r.key == key and r.state == ACTIVE), None)
        if target is None:
            if not text:
                return
            self._add_row(text, state, key)
        else:
            target.set_state(state, text)
        if text:
            self.status.setText(text)
        self._refresh()

    def add_done(self, text: str) -> None:
        """A stage that is already complete when it is reported (e.g. 'plan ready')."""
        text = str(text or "").strip()
        if not text:
            return
        if not self._active:
            self.start(text)
        self._add_row(text, DONE, None)
        self.status.setText(text)
        self._refresh()

    def step(self, description: str) -> None:
        self.begin(description)

    def update(self, status: str) -> None:
        self.begin(status)

    def complete(self, status: str = "انجام شد") -> None:
        if not self._active:
            return
        self._settle_active(DONE)
        self.status.setText(status)
        self._refresh(DONE)
        self._spin.stop()
        self.header_icon.tick(0)
        self._collapse_timer.start(1600)
        self._hide_timer.start(6000)

    def cancel(self, status: str = "درخواست متوقف شد") -> None:
        if not self._active:
            return
        self._settle_active(STOPPED)
        self.status.setText(status)
        self._refresh(STOPPED)
        self._spin.stop()
        self._hide_timer.start(6000)

    def fail(self, status: str = "با خطا متوقف شد") -> None:
        if not self._active:
            self.start(status)
        failed_any = False
        for row in self._rows:
            if row.state == ACTIVE:
                row.set_state(FAILED)
                failed_any = True
        if not failed_any:
            self._add_row(status, FAILED, None)
        self.status.setText(status)
        self.toggle.blockSignals(True)
        self.toggle.setChecked(True)
        self.toggle.setText("▾")
        self.toggle.blockSignals(False)
        self._refresh(FAILED)
        self._spin.stop()
        self._hide_timer.start(10000)

    def reset(self) -> None:
        self._stop_timers()
        self._spin.stop()
        self._active = False
        self._clear_rows()
        self.status.clear()
        self.count.hide()
        self.bar.set_value(0.0)
        self.hide()
