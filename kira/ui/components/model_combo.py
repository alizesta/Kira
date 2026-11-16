"""Reusable editable selector for locally installed Ollama models."""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox


class ModelCombo(QComboBox):
    """Editable installed-model list with a QLineEdit-compatible text API."""

    def __init__(self, text: str = "") -> None:
        super().__init__()
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setEditText(text)

    def text(self) -> str:
        return self.currentText()

    def setText(self, value: str) -> None:
        self.setEditText(str(value))

    def set_models(self, names) -> None:
        current = self.currentText()
        self.blockSignals(True)
        try:
            self.clear()
            self.addItems(list(names))
            self.setEditText(current)
        finally:
            self.blockSignals(False)
