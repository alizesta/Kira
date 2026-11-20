from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class ChatComposer(QFrame):
    """Jakob-familiar message composer with fluid sizing and safe resize behavior."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chatComposer")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setMinimumHeight(44)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(8, 6, 8, 6)
        root_layout.setSpacing(6)

        self.attachment_strip = QFrame(self)
        self.attachment_strip.setObjectName("composerAttachmentStrip")
        self.attachment_strip.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.attachment_layout = QHBoxLayout(self.attachment_strip)
        self.attachment_layout.setContentsMargins(4, 2, 4, 2)
        self.attachment_layout.setSpacing(6)
        self.attachment_strip.hide()
        root_layout.addWidget(self.attachment_strip)

        main_row = QHBoxLayout()
        main_row.setContentsMargins(0, 0, 0, 0)
        main_row.setSpacing(6)

        self.input_edit = QPlainTextEdit(self)
        self.input_edit.setObjectName("chatInput")
        self.input_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        self.input_edit.setMinimumSize(120, 34)
        self.input_edit.setMaximumHeight(160)
        main_row.addWidget(self.input_edit, 1)

        controls_col = QVBoxLayout()
        controls_col.setContentsMargins(0, 0, 0, 0)
        controls_col.setSpacing(4)

        actions_row = QHBoxLayout()
        actions_row.setContentsMargins(0, 0, 0, 0)
        actions_row.setSpacing(4)

        self.attach_btn = QPushButton("+", self)
        self.attach_btn.setObjectName("attachButton")
        self.attach_btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        self.attach_btn.setMinimumSize(32, 32)
        actions_row.addWidget(self.attach_btn)

        self.voice_btn = QPushButton("Mic", self)
        self.voice_btn.setObjectName("voiceButton")
        self.voice_btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        self.voice_btn.setMinimumSize(36, 32)
        actions_row.addWidget(self.voice_btn)

        self.send_btn = QPushButton("Send", self)
        self.send_btn.setObjectName("sendButton")
        self.send_btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        self.send_btn.setMinimumSize(44, 32)
        actions_row.addWidget(self.send_btn)

        controls_col.addLayout(actions_row)

        self.status_hint = QLabel("", self)
        self.status_hint.setObjectName("composerStatusHint")
        self.status_hint.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.status_hint.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.status_hint.setWordWrap(True)
        self.status_hint.hide()
        controls_col.addWidget(self.status_hint)

        main_row.addLayout(controls_col, 0)
        root_layout.addLayout(main_row)
