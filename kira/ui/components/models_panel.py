"""The "مدل‌ها" box: one table per tab (active / free / paid-or-unknown / archived).

Row data comes from kira.model_catalog.model_rows; this widget only draws rows and emits intents.
Model names are never elided: the name column sizes to its content and the table scrolls sideways if it must."""
from __future__ import annotations

import time
from collections.abc import Iterable

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget, QSizePolicy,
)

from ..shortcuts import delete_key
from ...model_catalog import TAB_ARCHIVED, TAB_TITLES, TABS

GREEN, ORANGE, GREY, RED = QColor("#3ddc97"), QColor("#ffb454"), QColor("#9aa0a6"), QColor("#ff6b6b")
PRICE = {"free": ("● رایگان", GREEN, "Provider رایگان بودن این مدل را اعلام کرده است"),
         "paid": ("● پولی", ORANGE, "Provider این مدل را رایگان اعلام نکرده است"),
         "unknown": ("● نامشخص", GREY, "Provider قیمت این مدل را گزارش نکرده؛ رایگان فرض نمی‌شود")}
COLUMNS = ("فعال", "مدل", "API", "قیمت", "وضعیت", "", "")


class ToggleSwitch(QAbstractButton):
    """The on/off switch every settings screen uses (familiar pattern) instead of a plain check box."""

    def __init__(self, checked=False, parent=None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)

    def sizeHint(self) -> QSize:
        return QSize(38, 20)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        track = QRectF(1, 1, self.width() - 2, self.height() - 2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(GREEN if self.isChecked() else QColor("#6b6f7b"))
        painter.setOpacity(1.0 if self.isEnabled() else 0.5)
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        d = track.height() - 6
        x = track.right() - d - 3 if self.isChecked() else track.left() + 3
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QRectF(x, track.top() + 3, d, d))


def price_pill(price: str) -> QWidget:
    """Rounded badge: green «رایگان», orange «پولی», grey «نامشخص»."""
    text, color, tip = PRICE[price]
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(2, 1, 2, 1)
    label = QLabel(text.replace("● ", ""))
    label.setAlignment(Qt.AlignCenter)
    label.setToolTip(tip)
    label.setProperty("price", price)
    label.setStyleSheet(
        f"QLabel{{color:{color.name()};border:1px solid {color.name()};border-radius:9px;padding:2px 10px;min-height:22px;"
        f"background:rgba({color.red()},{color.green()},{color.blue()},40);}}")
    label.setMinimumWidth(0)
    label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    lay.addWidget(label)
    box.setMinimumWidth(0)
    box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    return box


class ResponsiveModelsTable(QTableWidget):
    """Table whose columns always fit the visible viewport; long values remain available in tooltips."""

    NORMAL_RATIOS = (0.055, 0.36, 0.16, 0.10, 0.13, 0.095, 0.10)
    ARCHIVED_RATIOS = (0.0, 0.39, 0.18, 0.11, 0.15, 0.085, 0.08)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.fit_columns()

    def fit_columns(self) -> None:
        width = self.viewport().width()
        if width <= 0 or self.columnCount() != len(COLUMNS):
            return
        ratios = self.ARCHIVED_RATIOS if self.isColumnHidden(0) else self.NORMAL_RATIOS
        visible = [index for index, ratio in enumerate(ratios) if ratio > 0]
        widths = {index: int(width * ratios[index]) for index in visible}
        if visible:
            widths[visible[-1]] += width - sum(widths.values())
        for index in range(self.columnCount()):
            self.setColumnWidth(index, widths.get(index, 0))


class ModelsPanel(QGroupBox):
    toggle_requested = Signal(str, str, bool)      # provider id, model id, enabled
    test_requested = Signal(str, str)
    archive_requested = Signal(str, str)
    restore_requested = Signal(str, str)
    refresh_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__("مدل‌ها", parent)
        self._busy: set[tuple[str, str]] = set()
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("جستجو در نام مدل یا API…")
        self.search.textChanged.connect(self.apply_filter)
        self.refresh_btn = QPushButton("تازه‌سازی مدل‌ها")
        self.refresh_btn.clicked.connect(self.refresh_requested.emit)
        top.addWidget(self.search, 1)
        top.addWidget(self.refresh_btn)
        layout.addLayout(top)

        self.tabs = QTabWidget()
        self.tables: dict[str, QTableWidget] = {}
        for tab in TABS:
            table = self._make_table(tab)
            self.tables[tab] = table
            self.tabs.addTab(table, TAB_TITLES[tab])
        layout.addWidget(self.tabs)

        self.status = QLabel("")
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    # ------------------------------------------------------------------ build
    def _make_table(self, tab: str) -> QTableWidget:
        table = ResponsiveModelsTable(0, len(COLUMNS))
        table.setHorizontalHeaderLabels(COLUMNS)
        table.setLayoutDirection(Qt.LeftToRight)           # technical names read left-to-right in every column
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setTextElideMode(Qt.ElideMiddle)             # full values remain in the item tooltip
        table.setWordWrap(False)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        compact_font = table.font()
        compact_font.setPointSize(9)
        table.setFont(compact_font)
        table.verticalHeader().setDefaultSectionSize(36)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Fixed)
        header.setStretchLastSection(False)
        table.setMinimumHeight(210)
        table.setMaximumHeight(330)
        if tab != TAB_ARCHIVED:
            delete_key(table, lambda t=table: self._archive_selected(t))      # Delete = move the selected model to «منسوخ» (reversible)
        if tab == TAB_ARCHIVED:
            table.setColumnHidden(0, True)                  # nothing can be switched on from here: restore first
        return table

    def set_rows(self, rows: Iterable[dict], counts: dict[str, int] | None = None) -> None:
        rows = list(rows)
        for tab, table in self.tables.items():
            table.blockSignals(True)
            table.setRowCount(0)
            selected = [r for r in rows if tab in r["tabs"]]
            if tab == "active":
                selected.sort(key=lambda r: r["order"])             # the order the router tries them
            table.setRowCount(len(selected))
            for i, row in enumerate(selected):
                self._fill_row(table, i, tab, row)
                table.setRowHeight(i, 36)
            table.blockSignals(False)
            table.fit_columns()
        for index, tab in enumerate(TABS):
            n = (counts or {}).get(tab, sum(1 for r in rows if tab in r["tabs"]))
            self.tabs.setTabText(index, f"{TAB_TITLES[tab]} ({n})")
        self.apply_filter(self.search.text())

    def _fill_row(self, table: QTableWidget, i: int, tab: str, row: dict) -> None:
        key = (row["provider"], row["model"])
        if tab != TAB_ARCHIVED:
            switch = ToggleSwitch(row["enabled"])
            switch.setToolTip("روشن/خاموش کردن این مدل در Route")
            switch.toggled.connect(lambda on, k=key: self.toggle_requested.emit(k[0], k[1], bool(on)))
            holder = QWidget()
            hl = QHBoxLayout(holder)
            hl.setContentsMargins(6, 2, 6, 2)
            hl.addWidget(switch)
            table.setCellWidget(i, 0, holder)

        name = QTableWidgetItem(row["model"])
        name.setData(Qt.UserRole, key)
        name.setToolTip(f"{row['provider_label']}\n{row['model']}")
        table.setItem(i, 1, name)
        provider_item = QTableWidgetItem(row["provider_label"])
        provider_item.setToolTip(row["provider_label"])
        table.setItem(i, 2, provider_item)

        table.setCellWidget(i, 3, price_pill(row["price"]))
        sort_key = QTableWidgetItem()
        sort_key.setData(Qt.AccessibleTextRole, PRICE[row["price"]][0])
        table.setItem(i, 3, sort_key)

        table.setItem(i, 4, self._status_item(row, archived=tab == TAB_ARCHIVED))
        table.setCellWidget(i, 5, self._button("…" if key in self._busy else "تست", lambda k=key: self.test_requested.emit(*k),
                                               enabled=key not in self._busy, tip="یک درخواست خیلی کوتاه به همین مدل می‌فرستد"))
        if tab == TAB_ARCHIVED:
            if row["restorable"]:
                table.setCellWidget(i, 6, self._button("بازگردانی", lambda k=key: self.restore_requested.emit(*k),
                                                       tip="از منسوخ بیرون می‌آید (خاموش می‌ماند)"))
        else:
            table.setCellWidget(i, 6, self._button("منسوخ", lambda k=key: self.archive_requested.emit(*k),
                                                   tip="به تب «منسوخ / غیرفعال» منتقل و خاموش می‌شود"))

    def _archive_selected(self, table: QTableWidget) -> None:
        item = table.item(table.currentRow(), 1) if table.currentRow() >= 0 else None
        key = item.data(Qt.UserRole) if item is not None else None
        if key:
            self.archive_requested.emit(*key)

    @staticmethod
    def _when(ts) -> str:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "—"

    @classmethod
    def _status_item(cls, row: dict, *, archived: bool) -> QTableWidgetItem:
        test = row["test"]
        if archived:
            item = QTableWidgetItem("○ " + row["reason"])
            item.setForeground(QBrush(GREY))
        elif test and test["ok"]:
            ms = f" {test['ms']}ms" if test.get("ms") is not None else ""
            item = QTableWidgetItem("● سالم" + ms)
            item.setForeground(QBrush(GREEN))
        elif test:
            item = QTableWidgetItem("● ناموفق")
            item.setForeground(QBrush(RED))
        else:
            item = QTableWidgetItem("○ بدون تست")
            item.setForeground(QBrush(GREY))
        tip = []
        if archived:
            tip.append(row["reason"])
        if test:
            tip.append(f"آخرین تست: {cls._when(test.get('at'))}")
            if test.get("message"):
                tip.append(test["message"])
        if tip:
            item.setToolTip("\n".join(tip))
        return item

    @staticmethod
    def _button(text, slot, *, enabled=True, tip="") -> QWidget:
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(1, 1, 1, 1)
        lay.setSpacing(0)
        button = QPushButton(text)
        button.setStyleSheet("QPushButton{padding:2px 5px;min-height:22px;font-size:9pt;}")
        button.setMinimumWidth(0)
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        button.setEnabled(enabled)
        button.setToolTip(tip)
        button.clicked.connect(lambda: slot())
        lay.addWidget(button)
        box.setMinimumWidth(0)
        box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        return box

    # ------------------------------------------------------------------ interaction
    def set_testing(self, provider: str, model: str, on: bool) -> None:
        """Show the test button of one model as busy ('…') in every tab that lists it."""
        key = (provider, model)
        (self._busy.add if on else self._busy.discard)(key)
        for table in self.tables.values():
            for i in range(table.rowCount()):
                name = table.item(i, 1)
                if name is not None and name.data(Qt.UserRole) == key:
                    box = table.cellWidget(i, 5)
                    button = box.findChild(QPushButton) if box is not None else None
                    if button is not None:
                        button.setText("…" if on else "تست")
                        button.setEnabled(not on)

    def apply_filter(self, query: str) -> None:
        query = str(query or "").strip().casefold()
        for table in self.tables.values():
            for i in range(table.rowCount()):
                name, api = table.item(i, 1), table.item(i, 2)
                haystack = f"{name.text() if name else ''} {api.text() if api else ''}".casefold()
                table.setRowHidden(i, bool(query) and query not in haystack)
