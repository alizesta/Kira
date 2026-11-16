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

from ... import characters, mood, persona_memory


class MemoryDialog(QDialog):
    """View, edit and delete the active character's isolated long-term memory."""

    GROUPS = {"fact": "درباره‌ی تو", "moment": "لحظه / رویداد", "summary": "خلاصه‌ی گفتگوهای قدیمی"}

    def __init__(self, parent=None, character_id="kira"):
        super().__init__(parent)
        self.character_id = str(character_id or "kira")
        profiles = characters.all_profiles(getattr(parent, "settings", {}))
        self.character_name = str(profiles.get(self.character_id, {}).get("name") or self.character_id.title())
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
        current = mood.current()
        self.info.setText(
            f"حال‌وهوای فعلی همراه: {current['emotion']} ({current['intensity']}/100). "
            f"حافظه‌ی بلندمدت {self.character_name} جداست؛ هرچه اینجا نباشد در حافظه‌ی او ثبت نشده است. "
            "تاریخچه‌ی کوتاه‌مدت گفتگو همچنان مشترک است."
        )
        self.items.clear()
        with persona_memory.character_scope(self.character_id):
            saved_items = persona_memory.list_items()
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
            with persona_memory.character_scope(self.character_id):
                added = persona_memory.add_note(text)
            if added:
                self.refresh()

    def edit_item(self):
        item_id = self._selected()
        if not item_id:
            return
        with persona_memory.character_scope(self.character_id):
            current = next(
                (item["text"] for item in persona_memory.list_items() if item["id"] == item_id),
                "",
            )
        text, ok = QInputDialog.getText(self, "ویرایش", "متن:", QLineEdit.Normal, current)
        if ok:
            with persona_memory.character_scope(self.character_id):
                updated = persona_memory.update_item(item_id, text)
            if updated:
                self.refresh()

    def delete_item(self):
        item_id = self._selected()
        if item_id:
            with persona_memory.character_scope(self.character_id):
                deleted = persona_memory.delete_item(item_id)
            if deleted:
                self.refresh()

    def forget_all(self):
        question = (
            f"همه‌ی چیزهایی که {self.character_name} در حافظه‌ی بلندمدتش درباره‌ی تو نگه داشته پاک شود؟ "
            "تاریخچه‌ی کوتاه‌مدت گفتگو و حافظه‌ی شخصیت‌های دیگر دست‌نخورده می‌ماند."
        )
        if QMessageBox.question(self, "فراموش‌کردن همه", question) == QMessageBox.Yes:
            with persona_memory.character_scope(self.character_id):
                persona_memory.forget_all()
            if self.character_id == "kira":
                mood.reset()
            self.refresh()
