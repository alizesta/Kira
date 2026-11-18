"""Dialog for selecting discovered provider models."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)


class ModelPickerDialog(QDialog):
    """Select discovered provider models or add a model identifier manually."""

    def __init__(self, parent, title, models, existing, error=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(560)
        self.existing = set(existing)
        self._free = {m["id"]: m.get("free") for m in models}
        lay = QVBoxLayout(self)
        note = QLabel(
            "بودن یک مدل در فهرست به معنی تضمین دسترسی یا داشتن سهمیه نیست؛ فقط هنگام استفاده‌ی واقعی معلوم می‌شود. "
            "روی هر ردیف کلیک کن تا انتخاب شود. 🆓 = رایگان، 💲 = پولی (برای Gemini تشخیص تقریبی است)."
        )
        note.setObjectName("hint")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.error_lbl = QLabel(("✕ " + error) if error else "")
        self.error_lbl.setWordWrap(True)
        self.error_lbl.setVisible(bool(error))
        lay.addWidget(self.error_lbl)
        self.free_only = QCheckBox("فقط مدل‌های رایگان (و نامشخص) را نشان بده")
        has_paid = any(m.get("free") is False for m in models)
        self.free_only.setChecked(has_paid)
        self.free_only.setVisible(has_paid)
        self.free_only.toggled.connect(lambda *_: self.apply_filter())
        lay.addWidget(self.free_only)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("جست‌وجو در نام یا Model ID…")
        lay.addWidget(self.filter)
        self.list = QListWidget()
        self.list.setMinimumHeight(260)
        self.list.setLayoutDirection(Qt.LeftToRight)
        self.list.itemClicked.connect(self.toggle_item)
        lay.addWidget(self.list)
        for model in models:
            self.add_item(model["id"], model.get("name", ""), model.get("info", ""), free=model.get("free"))
        bulk = QHBoxLayout()
        all_btn = QPushButton("انتخاب همه‌ی نمایان")
        none_btn = QPushButton("برداشتن همه")
        all_btn.clicked.connect(lambda: self.set_visible_checked(True))
        none_btn.clicked.connect(lambda: self.set_visible_checked(False))
        bulk.addWidget(all_btn)
        bulk.addWidget(none_btn)
        bulk.addStretch(1)
        lay.addLayout(bulk)
        manual = QHBoxLayout()
        self.manual = QLineEdit()
        self.manual.setPlaceholderText("افزودن دستی: Model ID را بنویس")
        self.manual.setLayoutDirection(Qt.LeftToRight)
        add = QPushButton("افزودن دستی به فهرست")
        add.clicked.connect(self.add_manual)
        self.manual.returnPressed.connect(self.add_manual)
        manual.addWidget(self.manual, 1)
        manual.addWidget(add)
        lay.addLayout(manual)
        self.count_lbl = QLabel()
        lay.addWidget(self.count_lbl)
        box = QDialogButtonBox()
        self.ok_btn = box.addButton("افزودن به Route Manager", QDialogButtonBox.AcceptRole)
        box.addButton("انصراف", QDialogButtonBox.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self.filter.textChanged.connect(self.apply_filter)
        self.apply_filter()

    def add_item(self, mid, name="", info="", checked=False, free=None):
        mark = {True: "🆓 ", False: "💲 "}.get(free, "")
        item = QListWidgetItem(
            mark + (f"{name}  —  {mid}" if name else mid) + ("   (از قبل موجود)" if mid in self.existing else "")
        )
        item.setData(Qt.UserRole, mid)
        item.setToolTip(info or mid)
        self._free.setdefault(mid, free)
        if mid in self.existing:
            item.setFlags(Qt.ItemIsEnabled)
            item.setForeground(QBrush(QColor("#8d93ab")))
        else:
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self.list.addItem(item)
        return item

    def _selectable(self, item):
        return item.data(Qt.UserRole) not in self.existing

    def toggle_item(self, item):
        if self._selectable(item):
            item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)
            self.update_count()

    def set_visible_checked(self, on):
        for i in range(self.list.count()):
            item = self.list.item(i)
            if self._selectable(item) and not item.isHidden():
                item.setCheckState(Qt.Checked if on else Qt.Unchecked)
        self.update_count()

    def add_manual(self):
        mid = self.manual.text().strip()
        if mid.startswith("models/"):
            mid = mid[7:]
        if not mid:
            return
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(Qt.UserRole) == mid:
                if self._selectable(item):
                    item.setCheckState(Qt.Checked)
                    item.setHidden(False)
                self.manual.clear()
                self.update_count()
                return
        self.add_item(mid, "", "افزوده‌ی دستی", checked=True)
        self.manual.clear()
        self.apply_filter()

    def apply_filter(self, *_):
        text = self.filter.text().strip().lower()
        hide_paid = self.free_only.isChecked()
        for i in range(self.list.count()):
            item = self.list.item(i)
            mid = str(item.data(Qt.UserRole))
            missing = bool(text) and text not in item.text().lower() and text not in mid.lower()
            paid = hide_paid and self._free.get(mid) is False and item.checkState() != Qt.Checked
            item.setHidden(missing or paid)
        self.update_count()

    def selected_ids(self):
        return [
            self.list.item(i).data(Qt.UserRole)
            for i in range(self.list.count())
            if self._selectable(self.list.item(i)) and self.list.item(i).checkState() == Qt.Checked
        ]

    def update_count(self):
        shown = sum(1 for i in range(self.list.count()) if not self.list.item(i).isHidden())
        self.count_lbl.setText(f"{shown} مدل نمایان از {self.list.count()} · {len(self.selected_ids())} انتخاب‌شده")
