from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)


class ChatHeader(QFrame):
    """Familiar top chat bar with flexible title and non-clipping controls."""

    def __init__(self, title: str = "Kira", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chatHeader")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setMinimumHeight(38)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        self.title_label = QLabel(title, self)
        self.title_label.setObjectName("chatHeaderTitle")
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.title_label, 1)

        self.mode_badge = QLabel("", self)
        self.mode_badge.setObjectName("chatModeBadge")
        self.mode_badge.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
        self.mode_badge.hide()
        layout.addWidget(self.mode_badge, 0)

        self.new_chat_btn = QPushButton("New", self)
        self.new_chat_btn.setObjectName("newChatButton")
        self.new_chat_btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        self.new_chat_btn.setMinimumSize(36, 28)
        layout.addWidget(self.new_chat_btn, 0)

        self.settings_btn = QPushButton("Settings", self)
        self.settings_btn.setObjectName("settingsButton")
        self.settings_btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        self.settings_btn.setMinimumSize(44, 28)
        layout.addWidget(self.settings_btn, 0)
