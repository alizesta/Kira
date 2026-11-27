"""Native-feeling custom frame for Kira's frameless desktop window."""
from __future__ import annotations

import sys

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QToolButton


WINDOWS_RESIZE_HIT_CODES = {
    "left": 10,          # HTLEFT
    "right": 11,         # HTRIGHT
    "top": 12,            # HTTOP
    "top_left": 13,       # HTTOPLEFT
    "top_right": 14,      # HTTOPRIGHT
    "bottom": 15,         # HTBOTTOM
    "bottom_left": 16,    # HTBOTTOMLEFT
    "bottom_right": 17,   # HTBOTTOMRIGHT
}


def resize_region_at(x, y, width, height, border=8):
    """Return the native resize region for a point in the window's client area."""
    x, y = int(x), int(y)
    width, height, border = int(width), int(height), max(1, int(border))
    if width <= 0 or height <= 0 or x < 0 or y < 0 or x >= width or y >= height:
        return None

    left = x < border
    right = x >= width - border
    top = y < border
    bottom = y >= height - border

    if top and left:
        return "top_left"
    if top and right:
        return "top_right"
    if bottom and left:
        return "bottom_left"
    if bottom and right:
        return "bottom_right"
    if left:
        return "left"
    if right:
        return "right"
    if top:
        return "top"
    if bottom:
        return "bottom"
    return None


class _ResizeEventFilter(QObject):
    """Delegate edge resizing to the operating system for native resize behavior."""

    BORDER = 8

    def __init__(self, window):
        super().__init__(window)
        self._window = window

    def eventFilter(self, watched, event):
        if event.type() != QEvent.Type.MouseButtonPress:
            return False
        if event.button() != Qt.MouseButton.LeftButton:
            return False

        widget = watched if hasattr(watched, "parentWidget") else None
        while widget is not None and widget is not self._window:
            widget = widget.parentWidget()
        if widget is not self._window or self._window.isMaximized():
            return False

        point = event.globalPosition().toPoint()
        rect = self._window.frameGeometry()
        x, y = point.x(), point.y()
        edges = Qt.Edges()
        if x <= rect.left() + self.BORDER:
            edges |= Qt.Edge.LeftEdge
        elif x >= rect.right() - self.BORDER:
            edges |= Qt.Edge.RightEdge
        if y <= rect.top() + self.BORDER:
            edges |= Qt.Edge.TopEdge
        elif y >= rect.bottom() - self.BORDER:
            edges |= Qt.Edge.BottomEdge
        if not edges:
            return False

        handle = self._window.windowHandle()
        if handle is not None:
            handle.startSystemResize(edges)
            return True
        return False


class _TitleBar(QFrame):
    def __init__(self, window):
        super().__init__(window)
        self._window = window
        self.setObjectName("kiraCustomTitleBar")
        self.setFixedHeight(40)
        self.setStyleSheet(
            "#kiraCustomTitleBar { background: rgba(13, 13, 32, 238); "
            "border-bottom: 1px solid rgba(145, 105, 255, 95); }"
            "#kiraCustomTitleBar QLabel { color: #e9e5ff; font-size: 12px; "
            "font-weight: 700; letter-spacing: 2px; padding-left: 10px; }"
            "#kiraCustomTitleBar QToolButton { color: #d9d5f2; background: transparent; "
            "border: 0; border-radius: 6px; min-width: 38px; min-height: 28px; "
            "font-size: 15px; }"
            "#kiraCustomTitleBar QToolButton:hover { background: rgba(130, 110, 220, 75); }"
            "#kiraCustomTitleBar QToolButton#kiraCloseButton:hover { "
            "background: #c94062; color: white; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 8, 4)
        layout.setSpacing(4)

        icon = QLabel("◈")
        icon.setStyleSheet("color: #b99aff; font-size: 17px; padding: 0;")
        layout.addWidget(icon)
        title = QLabel("KIRA")
        layout.addWidget(title)
        layout.addStretch(1)

        self.minimize_button = self._button("—", "Minimize", window.showMinimized)
        self.maximize_button = self._button("□", "Maximize", self._toggle_maximize)
        self.close_button = self._button("×", "Close", window.close)
        self.close_button.setObjectName("kiraCloseButton")
        layout.addWidget(self.minimize_button)
        layout.addWidget(self.maximize_button)
        layout.addWidget(self.close_button)

    def _button(self, glyph, tooltip, callback):
        button = QToolButton(self)
        button.setText(glyph)
        button.setToolTip(tooltip)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(callback)
        return button

    def _toggle_maximize(self):
        if self._window.isMaximized():
            self._window.showNormal()
            self.maximize_button.setText("□")
            self.maximize_button.setToolTip("Maximize")
        else:
            self._window.showMaximized()
            self.maximize_button.setText("❐")
            self.maximize_button.setToolTip("Restore")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self._window.windowHandle()
            if handle is not None and handle.startSystemMove():
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_maximize()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


def create_custom_title_bar(window, parent):
    """Create Kira's title bar and install native OS edge-resize delegation once."""
    app = QApplication.instance()
    if (sys.platform != "win32" and app is not None
            and not getattr(window, "_kira_resize_filter", None)):
        resize_filter = _ResizeEventFilter(window)
        app.installEventFilter(resize_filter)
        window._kira_resize_filter = resize_filter
    return _TitleBar(window)
