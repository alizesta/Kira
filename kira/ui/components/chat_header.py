from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QWidget,
)


class ChatHeader(QFrame):
    """Familiar top chat bar with flexible title and non-clipping controls."""

    def __init__(self, title: str | QWidget = "Kira", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Older composition code passes the companion QToolButton as the first
        # argument; accept it as a widget instead of handing it to QLabel as text.
        title_widget = title if isinstance(title, QWidget) else None
        title_text = "Kira" if title_widget is not None else str(title)
        self.setObjectName("chatHeader")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setMinimumHeight(38)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        self.title_label = QLabel(title_text, self)
        self.title = self.title_label
        self.title_label.setObjectName("chatHeaderTitle")
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.title_label, 1)

        self.mode_badge = QLabel("", self)
        self.voice_mode_badge = self.mode_badge
        self.mode_badge.setObjectName("chatModeBadge")
        self.mode_badge.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
        self.mode_badge.hide()
        layout.addWidget(self.mode_badge, 0)

        self.mood_emotion_icon = QLabel("", self)
        self.mood_emotion_icon.setObjectName("moodEmotionIcon")
        self.mood_indicator = QLabel("", self)
        self.mood_indicator.setObjectName("moodIndicator")
        self.mood_emotion_icon.hide()
        self.mood_indicator.hide()

        self.companion_btn = title_widget
        if self.companion_btn is not None:
            self.companion_btn.setParent(self)
            layout.addWidget(self.companion_btn, 0)

