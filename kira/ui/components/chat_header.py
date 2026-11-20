"""Reusable chat header presentation owned by the Chat page."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget


class ChatHeader(QWidget):
    """Owns the chat title, emotion indicators and companion action button."""

    def __init__(self, companion_button: QWidget, parent=None) -> None:
        super().__init__(parent)
        header = QHBoxLayout(self)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)

        self.title = QLabel("Project Kira")
        self.title.setObjectName("title")
        header.addWidget(self.title)

        self.voice_mode_badge = QLabel("میکروفن خاموش")
        self.voice_mode_badge.setObjectName("voiceModeBadge")
        self.voice_mode_badge.setAlignment(Qt.AlignCenter)
        self.voice_mode_badge.setToolTip("وضعیت واقعی مکالمه صوتی: Gemini Live یا مسیر پشتیبان محلی STT/TTS.")
        self.voice_mode_badge.setStyleSheet(
            "QLabel#voiceModeBadge { background: rgba(12, 20, 43, 0.92); "
            "border: 1px solid rgba(105, 229, 255, 0.55); border-radius: 9px; "
            "padding: 5px 9px; color: #9FEFFF; font-size: 11px; }"
        )
        header.addWidget(self.voice_mode_badge)
        header.addStretch(1)

        self.mood_emotion_icon = QLabel()
        self.mood_emotion_icon.setObjectName("moodEmotionIcon")
        self.mood_emotion_icon.setAlignment(Qt.AlignCenter)
        self.mood_emotion_icon.setFixedSize(38, 38)
        self.mood_emotion_icon.setToolTip("احساس فعلی شخصیت فعال")
        self.mood_emotion_icon.setStyleSheet(
            "QLabel#moodEmotionIcon { background: rgba(12, 20, 43, 0.96); "
            "border: 1px solid rgba(105, 229, 255, 0.85); border-radius: 11px; padding: 2px; }"
        )
        header.addWidget(self.mood_emotion_icon)

        self.mood_indicator = QLabel()
        self.mood_indicator.setObjectName("moodIndicator")
        self.mood_indicator.setAlignment(Qt.AlignCenter)
        self.mood_indicator.hide()
        self.mood_indicator.setFixedSize(32, 32)
        self.mood_indicator.setToolTip("رفتار و انرژی فعلی شخصیت فعال")
        self.mood_indicator.setStyleSheet(
            "QLabel#moodIndicator { background: rgba(20, 24, 62, 0.92); "
            "border: 1px solid rgba(137, 112, 255, 0.88); border-radius: 11px; "
            "padding: 4px 7px; font-size: 16px; color: #F2E9FF; }"
        )
        header.addWidget(self.mood_indicator)

        self.companion_btn = companion_button
        header.addWidget(self.companion_btn)
