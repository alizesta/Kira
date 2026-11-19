"""MCP Registry discovery panel; network and installation work stay in the controller."""
from __future__ import annotations

import base64

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
)


class McpRegistryPanel(QGroupBox):
    search_requested = Signal()
    add_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__("افزونه‌ها و ابزارهای MCP", parent)
        form = QFormLayout(self)
        row = QHBoxLayout()
        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText("جستجوی سرور MCP (filesystem، github، browser)")
        self.search_btn = QPushButton("دریافت فهرست")
        self.search_btn.clicked.connect(self.search_requested.emit)
        self.query_edit.returnPressed.connect(self.search_requested.emit)
        row.addWidget(self.query_edit, 1)
        row.addWidget(self.search_btn)
        form.addRow(row)

        self.results = QListWidget()
        self.results.setMaximumHeight(150)
        self.results.setIconSize(QSize(36, 36))
        self.results.setSelectionMode(QAbstractItemView.SingleSelection)
        form.addRow(self.results)

        actions = QHBoxLayout()
        self.add_btn = QPushButton("افزودن سرور انتخاب‌شده")
        self.add_btn.clicked.connect(self.add_requested.emit)
        actions.addWidget(self.add_btn)
        form.addRow(actions)

        self.status = QLabel("در حال دریافت خودکار فهرست رسمی سرورهای MCP…")
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)
        form.addRow(self.status)

    @staticmethod
    def _server_icon(record, name):
        raw = record.get("_kira_icon_data")
        if raw:
            try:
                pixmap = QPixmap()
                if pixmap.loadFromData(base64.b64decode(raw, validate=True)) and not pixmap.isNull():
                    return QIcon(pixmap.scaled(36, 36, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            except Exception:
                pass
        # A branded monogram fallback keeps every registry entry visually identifiable.
        pixmap = QPixmap(36, 36)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        seed = sum(ord(char) for char in name)
        color = QColor.fromHsv(seed % 360, 145, 205)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(1, 1, 34, 34, 9, 9)
        painter.setPen(Qt.white)
        font = QFont()
        font.setBold(True)
        font.setPointSize(12)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignCenter, (name[:1] or "M").upper())
        painter.end()
        return QIcon(pixmap)

    def query(self) -> str:
        return self.query_edit.text().strip()

    def selected_record(self):
        item = self.results.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def set_searching(self, searching: bool) -> None:
        self.search_btn.setEnabled(not searching)
        if searching:
            self.status.setText("در حال دریافت فهرست رسمی MCP…")

    def set_status(self, message: str) -> None:
        self.status.setText(str(message))

    def show_results(self, records, error=None) -> None:
        self.set_searching(False)
        self.results.clear()
        if error:
            self.status.setText("دریافت فهرست ناموفق بود: " + str(error)[:240])
            return
        for record in records:
            server = record.get("server", record)
            name = str(server.get("name") or "Unnamed MCP")
            description = str(server.get("description") or "").replace("\\n", " ").strip()
            item = QListWidgetItem(self._server_icon(record, name), name)
            item.setData(Qt.UserRole, record)
            website = str(server.get("websiteUrl") or server.get("repository") or "")
            item.setToolTip(description + (("\\n\\n" + website) if website else ""))
            self.results.addItem(item)
        self.status.setText(f"{len(records)} سرور از رجیستری رسمی دریافت شد.")
