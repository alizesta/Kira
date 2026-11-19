"""API credential and model-filter form; validation and registration stay in the controller."""
from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton


class ApiAddPanel(QGroupBox):
    add_requested = Signal()
    filter_changed = Signal(int)

    def __init__(self, settings: dict, *, filter_options: Iterable[tuple[str, str]], parent=None) -> None:
        super().__init__("Add API", parent)
        settings = settings or {}
        form = QFormLayout(self)
        hint = QLabel(
            "فقط API Key را وارد کن؛ Kira خودش سرویس را (Groq، Mistral، Google AI Studio، Cloudflare یا OpenRouter) از روی پاسخ رسمی آن تشخیص می‌دهد، "
            "کلید را اعتبارسنجی می‌کند و مدل‌های قابل‌دسترسی را می‌گیرد. اگر سرویس با قطعیت شناسایی نشود، چیزی ثبت نمی‌شود."
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        form.addRow(hint)

        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("API Key")
        self.key_edit.setLayoutDirection(Qt.LeftToRight)
        self.add_btn = QPushButton("Add")
        key_row = QHBoxLayout()
        key_row.addWidget(self.key_edit, 1)
        key_row.addWidget(self.add_btn)
        form.addRow(key_row)

        self.account_edit = QLineEdit()
        self.account_edit.setPlaceholderText("Cloudflare Account ID (فقط اگر خواسته شد)")
        self.account_edit.setLayoutDirection(Qt.LeftToRight)
        self.account_edit.hide()
        form.addRow(self.account_edit)

        self.model_filter = QComboBox()
        for value, label in filter_options:
            self.model_filter.addItem(label, value)
        self.model_filter.setCurrentIndex(
            max(0, self.model_filter.findData(settings.get("model_filter_mode", "all")))
        )
        self.model_filter.setToolTip(
            "در حالت رایگان فقط مدل‌هایی نمایش داده می‌شوند که Provider رایگان‌بودنشان را اعلام کرده باشد. "
            "مدل‌های صوتی با قیمت نامشخص پنهان می‌مانند."
        )
        self.model_filter.currentIndexChanged.connect(self.filter_changed.emit)
        form.addRow("نمایش مدل‌ها", self.model_filter)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        form.addRow(self.status)
        self.add_btn.clicked.connect(self.add_requested.emit)
        self.key_edit.returnPressed.connect(self.add_requested.emit)
