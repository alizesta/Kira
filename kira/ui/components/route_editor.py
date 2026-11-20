"""Compact route and model selector with explicit application-intent signals."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from .switch_checkbox import SwitchCheckBox


class RouteEditor(QWidget):
    selection_changed = Signal()
    order_changed = Signal()
    failover_changed = Signal(bool)
    add_requested = Signal()
    delete_requested = Signal()
    select_manual_requested = Signal()
    select_auto_requested = Signal()
    test_requested = Signal()
    benchmark_requested = Signal(bool)
    details_changed = Signal()

    def __init__(self, settings: dict, *, model_combo_factory, parent=None) -> None:
        super().__init__(parent)
        settings = settings or {}
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        # A single frame replaces the previous nested Route and Details group boxes.
        panel = QGroupBox("مدیریت Route و انتخاب مدل")
        body = QVBoxLayout(panel)
        body.setContentsMargins(8, 6, 8, 7)
        body.setSpacing(5)

        self.route_list = QListWidget()
        self.route_list.setMinimumHeight(76)
        self.route_list.setMaximumHeight(126)
        self.route_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.route_list.setDefaultDropAction(Qt.MoveAction)
        self.route_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.route_list.setAlternatingRowColors(True)
        self.route_list.currentItemChanged.connect(lambda *_: self.selection_changed.emit())
        self.route_list.model().rowsMoved.connect(lambda *_: self.order_changed.emit())
        body.addWidget(self.route_list)

        # Reordering is drag-and-drop in the list; the first enabled route is the default, so there are no up/down/default buttons.
        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)
        self.route_add_btn = QPushButton("＋ افزودن")
        self.route_del_btn = QPushButton("حذف")
        self.route_use_btn = QPushButton("انتخاب دستی")
        self.route_auto_btn = QPushButton("خودکار")
        self.route_add_btn.clicked.connect(self.add_requested.emit)
        self.route_del_btn.clicked.connect(self.delete_requested.emit)
        self.route_use_btn.clicked.connect(self.select_manual_requested.emit)
        self.route_auto_btn.clicked.connect(self.select_auto_requested.emit)
        for button in (self.route_add_btn, self.route_del_btn, self.route_use_btn, self.route_auto_btn):
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        self.failover_chk = SwitchCheckBox("ادامه با مدل بعدی هنگام خطا")
        self.failover_chk.setChecked(bool(settings.get("failover_enabled", True)))
        self.failover_chk.toggled.connect(self.failover_changed.emit)
        toolbar.addWidget(self.failover_chk)
        body.addLayout(toolbar)

        self.route_manual_lbl = QLabel()
        self.route_manual_lbl.setObjectName("hint")
        self.route_manual_lbl.setWordWrap(True)
        body.addWidget(self.route_manual_lbl)

        # Model ID is the primary control: give it the full available width.
        model_row = QHBoxLayout()
        model_row.setSpacing(7)
        self.route_provider_lbl = QLabel("-")
        self.route_provider_lbl.setMinimumWidth(105)
        self.route_provider_lbl.setMaximumWidth(190)
        self.route_provider_lbl.setToolTip("Provider انتخاب‌شده")
        self.route_model_edit = model_combo_factory("")
        self.route_model_edit.setMinimumWidth(260)
        self.route_model_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        model_row.addWidget(self.route_provider_lbl)
        model_row.addWidget(self.route_model_edit, 1)
        self.route_enabled_chk = SwitchCheckBox("فعال")
        model_row.addWidget(self.route_enabled_chk)
        body.addLayout(model_row)

        limits_row = QHBoxLayout()
        limits_row.setSpacing(8)
        limits_row.addWidget(QLabel("Timeout"))
        self.route_timeout = QSpinBox()
        self.route_timeout.setRange(5, 600)
        self.route_timeout.setSuffix(" s")
        limits_row.addWidget(self.route_timeout)
        limits_row.addWidget(QLabel("Cooldown"))
        self.route_cooldown = QSpinBox()
        self.route_cooldown.setRange(0, 3600)
        self.route_cooldown.setSuffix(" s")
        limits_row.addWidget(self.route_cooldown)
        limits_row.addStretch(1)
        body.addLayout(limits_row)

        self.advanced_btn = QToolButton()
        self.advanced_btn.setText("تنظیمات پیشرفته (Ollama)")
        self.advanced_btn.setCheckable(True)
        self.advanced_btn.setChecked(False)
        self.advanced_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.advanced_btn.setArrowType(Qt.RightArrow)
        self.advanced_body = QWidget()
        advanced = QFormLayout(self.advanced_body)
        advanced.setContentsMargins(0, 2, 0, 0)
        advanced.setHorizontalSpacing(8)
        advanced.setVerticalSpacing(3)
        self.route_ctx = QSpinBox()
        self.route_ctx.setRange(0, 32768)
        self.route_ctx.setSingleStep(1024)
        self.route_ctx.setSpecialValueText("پیش‌فرض Provider")
        self.route_predict = QSpinBox()
        self.route_predict.setRange(0, 4096)
        self.route_predict.setSingleStep(64)
        self.route_predict.setSpecialValueText("پیش‌فرض Provider")
        advanced.addRow("Context", self.route_ctx)
        advanced.addRow("Num Predict", self.route_predict)
        self.advanced_body.setVisible(False)
        self.advanced_btn.toggled.connect(self.advanced_body.setVisible)
        self.advanced_btn.toggled.connect(
            lambda on: self.advanced_btn.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        )
        body.addWidget(self.advanced_btn)
        body.addWidget(self.advanced_body)

        self.route_status = QLabel("Route‌ای انتخاب نشده.")
        self.route_status.setWordWrap(True)
        body.addWidget(self.route_status)

        actions = QHBoxLayout()
        actions.setSpacing(4)
        self.route_test_btn = QPushButton("تست اتصال")
        self.route_test_btn.clicked.connect(self.test_requested.emit)
        self.route_bench_btn = QPushButton("Benchmark ▾")
        bench_menu = QMenu(self.route_bench_btn)
        bench_menu.addAction("فقط این Route", lambda: self.benchmark_requested.emit(False))
        bench_menu.addAction("همه Routeها", lambda: self.benchmark_requested.emit(True))
        self.route_bench_btn.setMenu(bench_menu)
        actions.addWidget(self.route_test_btn)
        actions.addWidget(self.route_bench_btn)
        actions.addStretch(1)
        body.addLayout(actions)

        self.bench_out = QTextEdit()
        self.bench_out.setReadOnly(True)
        self.bench_out.setMinimumHeight(48)
        self.bench_out.setMaximumHeight(110)
        self.bench_out.setLayoutDirection(Qt.LeftToRight)
        self.bench_out.setVisible(False)
        self.bench_out.textChanged.connect(lambda: self.bench_out.setVisible(bool(self.bench_out.toPlainText().strip())))
        body.addWidget(self.bench_out)

        self.route_enabled_chk.toggled.connect(lambda *_: self.details_changed.emit())
        for widget in (self.route_timeout, self.route_cooldown, self.route_ctx, self.route_predict):
            widget.valueChanged.connect(lambda *_: self.details_changed.emit())
        self.route_model_edit.lineEdit().editingFinished.connect(self.details_changed.emit)
        self.route_model_edit.activated.connect(lambda *_: self.details_changed.emit())

        root.addWidget(panel)
