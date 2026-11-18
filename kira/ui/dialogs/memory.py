"""Character-scoped long-term memory management dialog."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ...core.interfaces.memory_service import MemoryService
from ...core.interfaces.mood_service import MoodService


class MemoryDialog(QDialog):
    """View, edit and delete the active character's isolated long-term memory."""

    GROUPS = {"fact": "درباره‌ی تو", "moment": "لحظه / رویداد", "summary": "خلاصه‌ی گفتگوهای قدیمی"}

    def __init__(
        self,
        parent=None,
        character_id="kira",
        *,
        character_name=None,
        memory_service: MemoryService,
        mood_service: MoodService,
    ):
        super().__init__(parent)
        self.character_id = str(character_id or "kira")
        self.character_name = str(character_name or self.character_id.title())
        self.memory_service = memory_service
        self.mood_service = mood_service
        if self.memory_service is None or self.mood_service is None:
            raise ValueError("MemoryDialog requires injected memory_service and mood_service")
        self.setWindowTitle(f"حافظه‌ی {self.character_name}")
        self.resize(680, 480)
        lay = QVBoxLayout(self)
        self.info = QLabel()
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.items = QListWidget()
        self.items.setSelectionMode(QAbstractItemView.SingleSelection)
        lay.addWidget(self.items, 1)
        row = QHBoxLayout()
        for text, fn in (
            ("افزودن یادداشت", self.add_note),
            ("ویرایش", self.edit_item),
            ("حذف", self.delete_item),
            ("فراموش‌کردن همه", self.forget_all),
        ):
            btn = QPushButton(text)
            btn.clicked.connect(lambda checked=False, f=fn: f())
            row.addWidget(btn)
        lay.addLayout(row)
        close = QPushButton("بستن")
        close.clicked.connect(self.accept)
        lay.addWidget(close)
        self.refresh()

    def refresh(self):
        current = self.mood_service.current()
        self.info.setText(
            f"حال‌وهوای فعلی همراه: {current['emotion']} ({current['intensity']}/100). "
            f"حافظه‌ی بلندمدت {self.character_name} جداست؛ هرچه اینجا نباشد در حافظه‌ی او ثبت نشده است. "
            "تاریخچه‌ی کوتاه‌مدت گفتگو همچنان مشترک است."
        )
        self.items.clear()
        saved_items = self.memory_service.list_items(self.character_id)
        for memory_item in saved_items:
            row = QListWidgetItem(
                f"[{self.GROUPS.get(memory_item['group'], memory_item['group'])}] {memory_item['text']}"
            )
            row.setData(Qt.UserRole, memory_item["id"])
            self.items.addItem(row)

    def _selected(self):
        item = self.items.currentItem()
        return item.data(Qt.UserRole) if item else None

    def add_note(self):
        text, ok = QInputDialog.getText(self, "یادداشت جدید", f"چه چیزی را {self.character_name} یادش بماند؟")
        if ok:
            added = self.memory_service.add_note(self.character_id, text)
            if added:
                self.refresh()

    def edit_item(self):
        item_id = self._selected()
        if not item_id:
            return
        current = next(
            (item["text"] for item in self.memory_service.list_items(self.character_id) if item["id"] == item_id),
            "",
        )
        text, ok = QInputDialog.getText(self, "ویرایش", "متن:", QLineEdit.Normal, current)
        if ok:
            updated = self.memory_service.update_item(self.character_id, item_id, text)
            if updated:
                self.refresh()

    def delete_item(self):
        item_id = self._selected()
        if item_id:
            deleted = self.memory_service.delete_item(self.character_id, item_id)
            if deleted:
                self.refresh()

    def forget_all(self):
        question = (
            f"همه‌ی چیزهایی که {self.character_name} در حافظه‌ی بلندمدتش درباره‌ی تو نگه داشته پاک شود؟ "
            "تاریخچه‌ی کوتاه‌مدت گفتگو و حافظه‌ی شخصیت‌های دیگر دست‌نخورده می‌ماند."
        )
        if QMessageBox.question(self, "فراموش‌کردن همه", question) == QMessageBox.Yes:
            try:
                self.memory_service.forget_all(self.character_id)
            except Exception:
                QMessageBox.warning(
                    self,
                    "پاک‌سازی کامل نشد",
                    "حذف همه‌ی داده‌های حافظه کامل نشد؛ ممکن است بخشی از اطلاعات باقی مانده باشد. جزئیات خطا در گزارش برنامه ثبت شده است.",
                )
                self.refresh()
                return
            if self.character_id == "kira":
                self.mood_service.reset()
            self.refresh()
