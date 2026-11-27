"""The "مدل‌ها" box: one table per tab (active / free / paid-or-unknown / archived).

Row data comes from kira.model_catalog.model_rows; this widget only draws rows and emits intents.
Columns fit the viewport without horizontal scrolling; full cell values remain available in tooltips."""
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


from .fit_height import fit_height


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


def price_pill(price: str, tip: str = "") -> QWidget:
    """Rounded badge: green «رایگان», orange «پولی», grey «نامشخص»."""
    text, color, tip_default = PRICE[price]
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(2, 1, 2, 1)
    lay.setSpacing(0)
    lay.setAlignment(Qt.AlignCenter)
    label = QLabel(text.replace("● ", ""))
    label.setAlignment(Qt.AlignCenter)
    label.setToolTip(tip or tip_default)
    label.setProperty("price", price)
    label.setStyleSheet(
        f"QLabel{{color:{color.name()};border:1px solid {color.name()};border-radius:9px;padding:2px 10px;min-height:22px;"
        f"background:rgba({color.red()},{color.green()},{color.blue()},40);}}")
    label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    label.setFixedSize(label.sizeHint())
    lay.addWidget(label, 0, Qt.AlignCenter)
    box.setMinimumSize(0, 0)
    box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    return box


class ResponsiveModelsTable(QTableWidget):
    """Table whose columns always fit the visible viewport; long values remain available in tooltips."""

    NORMAL_RATIOS = (0.055, 0.33, 0.15, 0.105, 0.13, 0.105, 0.125)
    ARCHIVED_RATIOS = (0.0, 0.36, 0.17, 0.11, 0.15, 0.09, 0.12)

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
            fit_height(table, len(selected), max_height=330)
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
        members = list(row.get("members") or [row])
        member_keys = tuple((member["provider"], member["model"]) for member in members)
        toggle_keys = tuple(row.get("toggle_member_keys") or member_keys)
        archived_members = [
            member for member in members if TAB_ARCHIVED in member.get("tabs", [])
        ]
        restorable_members = [
            member for member in archived_members if member.get("restorable")
        ]
        busy = any(key in self._busy for key in member_keys)
        if tab != TAB_ARCHIVED:
            switch = ToggleSwitch(row["enabled"])
            switch.setToolTip("روشن/خاموش کردن این مدل در تمام APIهای غیرآرشیوشده")
            switch.toggled.connect(lambda on, keys=toggle_keys: [
                self.toggle_requested.emit(provider, model, bool(on)) for provider, model in keys
            ])
            holder = QWidget()
            hl = QHBoxLayout(holder)
            hl.setContentsMargins(6, 2, 6, 2)
            hl.addWidget(switch)
            table.setCellWidget(i, 0, holder)

        name = QTableWidgetItem(row["model"])
        name.setData(Qt.UserRole, member_keys)
        name.setToolTip("\n".join(
            f"{member['provider_label']} · {member['model']}" for member in members
        ))
        table.setItem(i, 1, name)
        provider_item = QTableWidgetItem(row["provider_label"])
        provider_item.setToolTip("\n".join(row.get("provider_labels") or [row["provider_label"]]))
        table.setItem(i, 2, provider_item)

        table.setCellWidget(i, 3, price_pill(row["price"], row.get("price_tooltip", "")))
        sort_key = QTableWidgetItem()
        sort_key.setData(Qt.AccessibleTextRole, PRICE[row["price"]][0])
        table.setItem(i, 3, sort_key)

        table.setItem(i, 4, self._status_item(row, archived=tab == TAB_ARCHIVED))
        table.setCellWidget(i, 5, self._button(
            "…" if busy else "تست",
            lambda keys=member_keys: [self.test_requested.emit(*key) for key in keys],
            enabled=not busy, tip="برای هر API متصل به این مدل یک درخواست کوتاه می‌فرستد"
        ))
        if restorable_members:
            table.setCellWidget(i, 6, self._button(
                f"بازگردانی ({len(restorable_members)} API)" if len(members) > 1 else "بازگردانی",
                lambda group=tuple(restorable_members): [
                    self.restore_requested.emit(member["provider"], member["model"])
                    for member in group
                ],
                tip="APIهای آرشیوشدهٔ قابل‌بازگردانی از منسوخ خارج می‌شوند (خاموش می‌مانند)"
            ))
        elif tab != TAB_ARCHIVED:
            table.setCellWidget(i, 6, self._button(
                "منسوخ",
                lambda keys=member_keys: [self.archive_requested.emit(*key) for key in keys],
                tip="تمام APIهای این مدل به تب «منسوخ / غیرفعال» منتقل و خاموش می‌شوند"
            ))

    def _archive_selected(self, table: QTableWidget) -> None:
        item = table.item(table.currentRow(), 1) if table.currentRow() >= 0 else None
        key = item.data(Qt.UserRole) if item is not None else None
        if key:
            for provider, model in key:
                self.archive_requested.emit(provider, model)

    @staticmethod
    def _when(ts) -> str:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "—"

    @classmethod
    def _status_item(cls, row: dict, *, archived: bool) -> QTableWidgetItem:
        test = row["test"]
        if archived:
            item = QTableWidgetItem("○ " + (row["reason"] or "منسوخ / غیرفعال"))
            item.setForeground(QBrush(GREY))
        elif test and test.get("ok") is None:
            item = QTableWidgetItem("◐ " + (test.get("message") or "تست ناقص"))
            item.setForeground(QBrush(ORANGE))
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
        if row.get("reason"):
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
        lay.setContentsMargins(2, 1, 2, 1)
        lay.setSpacing(0)
        lay.setAlignment(Qt.AlignCenter)
        button = QPushButton(text)
        button.setStyleSheet("QPushButton{padding:2px 5px;min-height:20px;font-size:8pt;}")
        button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        button.setFixedSize(button.sizeHint())
        button.setEnabled(enabled)
        button.setToolTip(tip)
        button.clicked.connect(lambda: slot())
        lay.addWidget(button, 0, Qt.AlignCenter)
        box.setMinimumSize(0, 0)
        box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        return box

    # ------------------------------------------------------------------ interaction
    def set_testing(self, provider: str, model: str, on: bool) -> None:
        """Show the test button of one model as busy ('…') in every tab that lists it."""
        key = (provider, model)
        (self._busy.add if on else self._busy.discard)(key)
        for table in self.tables.values():
            for i in range(table.rowCount()):
                name = table.item(i, 1)
                member_keys = name.data(Qt.UserRole) if name is not None else ()
                if member_keys and key in member_keys:
                    box = table.cellWidget(i, 5)
                    button = box.findChild(QPushButton) if box is not None else None
                    if button is not None:
                        busy = any(member_key in self._busy for member_key in member_keys)
                        button.setText("…" if busy else "تست")
                        button.setEnabled(not busy)

    def apply_filter(self, query: str) -> None:
        query = str(query or "").strip().casefold()
        for table in self.tables.values():
            for i in range(table.rowCount()):
                name, api = table.item(i, 1), table.item(i, 2)
                haystack = f"{name.text() if name else ''} {api.text() if api else ''}".casefold()
                table.setRowHidden(i, bool(query) and query not in haystack)
