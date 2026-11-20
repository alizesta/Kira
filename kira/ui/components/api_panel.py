"""The "API" box: add a key, then the list of registered APIs with per-row refresh / delete.

Validation, registration and the dialogs stay in the controller; this widget only shows rows and emits intents."""
from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..shortcuts import delete_key


class ApiPanel(QGroupBox):
    add_requested = Signal()
    refresh_requested = Signal(str)
    delete_requested = Signal(str)
    edit_requested = Signal(str)
    custom_requested = Signal()

    COLUMNS = ("API", "وضعیت", "مدل‌های در دسترس", "فعال", "آخرین بررسی", "")

    def __init__(self, parent=None) -> None:
        super().__init__("API", parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        hint = QLabel(
            "فقط API Key را وارد کن؛ Kira سرویس را (Groq، Mistral، Google AI Studio، Cloudflare یا OpenRouter) خودش تشخیص می‌دهد، "
            "کلید را اعتبارسنجی می‌کند و مدل‌ها را می‌گیرد. برای تغییر کلید روی ردیف دابل‌کلیک کن."
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("API Key")
        self.key_edit.setLayoutDirection(Qt.LeftToRight)
        self.add_btn = QPushButton("افزودن")
        row = QHBoxLayout()
        row.addWidget(self.key_edit, 1)
        row.addWidget(self.add_btn)
        layout.addLayout(row)

        self.account_edit = QLineEdit()
        self.account_edit.setPlaceholderText("Cloudflare Account ID (فقط اگر خواسته شد)")
        self.account_edit.setLayoutDirection(Qt.LeftToRight)
        self.account_edit.hide()
        layout.addWidget(self.account_edit)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setMinimumHeight(120)
        self.table.setMaximumHeight(210)
        self.table.cellDoubleClicked.connect(lambda row, _col: self._emit_for_row(row, self.edit_requested))
        delete_key(self.table, lambda: self._emit_for_row(self.table.currentRow(), self.delete_requested))   # Delete asks before removing
        layout.addWidget(self.table)

        self.custom_btn = QPushButton("＋ Provider سفارشی / سرور سازگار با OpenAI (پیشرفته)")
        self.custom_btn.setFlat(True)
        self.custom_btn.clicked.connect(self.custom_requested.emit)
        layout.addWidget(self.custom_btn, 0, Qt.AlignLeft)

        self.add_btn.clicked.connect(self.add_requested.emit)
        self.key_edit.returnPressed.connect(self.add_requested.emit)

    # ------------------------------------------------------------------ rows
    def _emit_for_row(self, row, signal):
        item = self.table.item(row, 0) if row >= 0 else None
        if item is not None and item.data(Qt.UserRole):
            signal.emit(item.data(Qt.UserRole))

    def selected_id(self) -> str:
        item = self.table.item(self.table.currentRow(), 0) if self.table.currentRow() >= 0 else None
        return item.data(Qt.UserRole) if item is not None else ""

    def set_rows(self, rows: Iterable[dict], *, status_text, time_text, select: str = "") -> None:
        """``rows`` come from api_manager.api_rows; ``status_text`` / ``time_text`` map status code / timestamp to display text."""
        rows = list(rows)
        keep = select or self.selected_id()
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            name = f"{r['label']}  ({r['key']})" if r["key"] else r["label"]
            status = status_text(r["status"]) + ("" if r["enabled"] else " · خاموش")
            cells = [name, status, "Unknown" if r["accessible"] is None else str(r["accessible"]),
                     str(r["active"]), time_text(r["checked_at"])]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.UserRole, r["id"])
                if r["error"] and col == 1:
                    item.setToolTip(r["error"])
                self.table.setItem(i, col, item)
            self.table.setCellWidget(i, len(cells), self._row_buttons(r["id"]))
            self.table.setRowHeight(i, 34)
        self.table.blockSignals(False)
        target = next((i for i, r in enumerate(rows) if r["id"] == keep), 0 if rows else -1)
        if target >= 0:
            self.table.selectRow(target)

    def _row_buttons(self, pid: str) -> QWidget:
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(2, 1, 2, 1)
        lay.setSpacing(4)
        refresh = QPushButton("تازه‌سازی")
        refresh.setToolTip("کلید دوباره اعتبارسنجی و فهرست مدل‌ها دوباره گرفته می‌شود")
        refresh.clicked.connect(lambda: self.refresh_requested.emit(pid))
        delete = QPushButton("حذف")
        delete.clicked.connect(lambda: self.delete_requested.emit(pid))
        lay.addWidget(refresh)
        lay.addWidget(delete)
        return box
