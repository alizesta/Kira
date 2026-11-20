"""Ollama provider settings widget; URL validation and persistence stay in the controller."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton


class OllamaProviderPanel(QGroupBox):
    enabled_changed = Signal(bool)
    cancel_requested = Signal()
    save_requested = Signal()

    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__("Ollama · Local", parent)
        local_cfg = (settings or {}).get("providers", {}).get("ollama", {})
        form = QFormLayout(self)
        self.enabled = QCheckBox("فعال بودن Provider محلی Ollama")
        self.enabled.setChecked(bool(local_cfg.get("enabled", True)))
        self.enabled.toggled.connect(self.enabled_changed.emit)
        form.addRow(self.enabled)

        self.url_edit = QLineEdit(str((settings or {}).get("ollama_url", "http://localhost:11434")))
        self.url_edit.setReadOnly(True)
        form.addRow("Base URL", self.url_edit)
        self.edit_btn = QPushButton("ویرایش")
        self.save_btn = QPushButton("ذخیره")
        self.cancel_btn = QPushButton("انصراف")
        self.save_btn.hide()
        self.cancel_btn.hide()
        row = QHBoxLayout()
        for button in (self.edit_btn, self.save_btn, self.cancel_btn):
            row.addWidget(button)
        form.addRow(row)

        self.edit_btn.clicked.connect(lambda: self.set_edit_mode(True))
        self.cancel_btn.clicked.connect(self.cancel_requested.emit)
        self.save_btn.clicked.connect(self.save_requested.emit)

        note = QLabel(
            "Context، Keep-alive و Num Predict پیش‌فرض Ollama در تب «دستیار» است؛ "
            "هر Route محلی می‌تواند Context/Num Predict خودش را هم داشته باشد. "
            "مدل‌های نصب‌شده را با «یافتن مدل‌های Ollama» بالای صفحه بیاور."
        )
        note.setObjectName("hint")
        note.setWordWrap(True)
        form.addRow(note)

    def set_edit_mode(self, enabled: bool, reset_url: str | None = None) -> None:
        self.url_edit.setReadOnly(not enabled)
        self.edit_btn.setVisible(not enabled)
        self.save_btn.setVisible(enabled)
        self.cancel_btn.setVisible(enabled)
        if not enabled and reset_url is not None:
            self.url_edit.setText(str(reset_url))
