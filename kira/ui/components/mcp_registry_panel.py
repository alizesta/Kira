"""MCP Registry discovery panel; network and installation work stay in the controller."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QWidget,
)


class McpRegistryPanel(QGroupBox):
    search_requested = Signal()
    add_requested = Signal()
    refresh_models_requested = Signal()

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
        self.results.setMaximumHeight(105)
        self.results.setSelectionMode(QListWidget.SingleSelection)
        form.addRow(self.results)

        actions = QHBoxLayout()
        self.add_btn = QPushButton("افزودن سرور انتخاب‌شده")
        self.add_btn.clicked.connect(self.add_requested.emit)
        self.refresh_btn = QPushButton("تازه‌سازی مدل‌ها")
        self.refresh_btn.clicked.connect(self.refresh_models_requested.emit)
        actions.addWidget(self.add_btn)
        actions.addWidget(self.refresh_btn)
        form.addRow(actions)

        self.status = QLabel("در حال دریافت خودکار فهرست رسمی سرورهای MCP…")
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)
        form.addRow(self.status)

    def query(self) -> str:
        return self.query_edit.text().strip()

    def selected_record(self):
        item = self.results.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def set_searching(self, searching: bool) -> None:
        self.search_btn.setEnabled(not searching)
        if searching:
            self.status.setText("در حال دریافت فهرست رسمی MCP…")

    def set_refreshing(self, refreshing: bool) -> None:
        self.refresh_btn.setEnabled(not refreshing)

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
            description = str(server.get("description") or "").replace("\\n", " ")
            item = QListWidgetItem(name + (" · " + description[:90] if description else ""))
            item.setData(Qt.UserRole, record)
            self.results.addItem(item)
        self.status.setText(f"{len(records)} سرور از رجیستری رسمی دریافت شد.")
