"""Keyboard shortcuts every desktop app has (Jakob's law). Window-wide ones live here; list-specific Delete keys live in their widgets."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut


def delete_key(widget, callback) -> QShortcut:
    """Delete on the focused widget (list / table / chat view) runs ``callback``; it does nothing while another widget has focus."""
    shortcut = QShortcut(QKeySequence(Qt.Key_Delete), widget)
    shortcut.setContext(Qt.WidgetShortcut)
    shortcut.activated.connect(callback)
    return shortcut


def install_window_shortcuts(window, *, go_tab, focus_input, stop_generation, tab_count: int, settings_tab: int) -> list[QShortcut]:
    """Ctrl+L focus the message box · Esc stop the answer · Ctrl+1..N switch tab · Ctrl+, open the connections/model settings."""
    made = []

    def add(keys, callback):
        shortcut = QShortcut(QKeySequence(keys), window)
        shortcut.setContext(Qt.WindowShortcut)
        shortcut.activated.connect(callback)
        made.append(shortcut)

    add("Ctrl+L", focus_input)
    add("Esc", stop_generation)
    add("Ctrl+,", lambda: go_tab(settings_tab))
    for index in range(min(tab_count, 9)):
        add(f"Ctrl+{index + 1}", lambda i=index: go_tab(i))
    return made
