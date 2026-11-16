"""Route/failover editor widget with explicit application-intent signals."""
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
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class RouteEditor(QWidget):
    selection_changed = Signal()
    order_changed = Signal()
    failover_changed = Signal(bool)
    move_requested = Signal(int)
    add_requested = Signal()
    delete_requested = Signal()
    default_requested = Signal()
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
        root.setSpacing(6)

        route_box = QGroupBox("Routeها و اولویت Failover")
        route_form = QFormLayout(route_box)
        route_form.setContentsMargins(8, 6, 8, 6)
        route_form.setHorizontalSpacing(8)
        route_form.setVerticalSpacing(5)
        self.route_list = QListWidget()
        self.route_list.setMinimumHeight(125)
        self.route_list.setMaximumHeight(190)
        self.route_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.route_list.setDefaultDropAction(Qt.MoveAction)
        self.route_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.route_list.currentItemChanged.connect(lambda *_: self.selection_changed.emit())
        self.route_list.model().rowsMoved.connect(lambda *_: self.order_changed.emit())
        route_form.addRow(self.route_list)

        self.route_manual_lbl = QLabel()
        self.route_manual_lbl.setObjectName("hint")
        route_form.addRow(self.route_manual_lbl)
        self.failover_chk = QCheckBox("در صورت خطا به مدل بعدی برو")
        self.failover_chk.setChecked(bool(settings.get("failover_enabled", True)))
        self.failover_chk.toggled.connect(self.failover_changed.emit)
        route_form.addRow(self.failover_chk)

        buttons = QHBoxLayout()
        self.route_up_btn = QPushButton("▲")
        self.route_down_btn = QPushButton("▼")
        self.route_add_btn = QPushButton("افزودن Route")
        self.route_del_btn = QPushButton("حذف")
        self.route_default_btn = QPushButton("پیش‌فرض")
        self.route_use_btn = QPushButton("انتخاب دستی")
        self.route_auto_btn = QPushButton("خودکار")
        self.route_up_btn.clicked.connect(lambda: self.move_requested.emit(-1))
        self.route_down_btn.clicked.connect(lambda: self.move_requested.emit(1))
        self.route_add_btn.clicked.connect(self.add_requested.emit)
        self.route_del_btn.clicked.connect(self.delete_requested.emit)
        self.route_default_btn.clicked.connect(self.default_requested.emit)
        self.route_use_btn.clicked.connect(self.select_manual_requested.emit)
        self.route_auto_btn.clicked.connect(self.select_auto_requested.emit)
        for button in (
            self.route_up_btn, self.route_down_btn, self.route_add_btn,
            self.route_del_btn, self.route_default_btn, self.route_use_btn,
            self.route_auto_btn,
        ):
            buttons.addWidget(button)
        route_form.addRow(buttons)

        details_box = QGroupBox("جزئیات Route انتخاب‌شده")
        details_form = QFormLayout(details_box)
        details_form.setContentsMargins(8, 6, 8, 6)
        details_form.setHorizontalSpacing(8)
        details_form.setVerticalSpacing(5)
        self.route_provider_lbl = QLabel("-")
        details_form.addRow("Provider", self.route_provider_lbl)
        self.route_model_edit = model_combo_factory("")
        details_form.addRow("Model ID", self.route_model_edit)
        self.route_enabled_chk = QCheckBox("فعال")
        details_form.addRow(self.route_enabled_chk)
        self.route_timeout = QSpinBox()
        self.route_timeout.setRange(5, 600)
        self.route_timeout.setSuffix(" s")
        details_form.addRow("Timeout", self.route_timeout)
        self.route_cooldown = QSpinBox()
        self.route_cooldown.setRange(0, 3600)
        self.route_cooldown.setSuffix(" s")
        details_form.addRow("Cooldown", self.route_cooldown)
        self.route_ctx = QSpinBox()
        self.route_ctx.setRange(0, 32768)
        self.route_ctx.setSingleStep(1024)
        self.route_ctx.setSpecialValueText("پیش‌فرض Provider")
        self.route_predict = QSpinBox()
        self.route_predict.setRange(0, 4096)
        self.route_predict.setSingleStep(64)
        self.route_predict.setSpecialValueText("پیش‌فرض Provider")
        details_form.addRow("Context (Ollama)", self.route_ctx)
        details_form.addRow("Num Predict (Ollama)", self.route_predict)
        self.route_status = QLabel("Route‌ای انتخاب نشده.")
        self.route_status.setWordWrap(True)
        details_form.addRow(self.route_status)

        actions = QHBoxLayout()
        self.route_test_btn = QPushButton("تست اتصال")
        self.route_bench_btn = QPushButton("Benchmark این Route")
        self.route_bench_all_btn = QPushButton("Benchmark همه‌ی مدل‌ها")
        self.route_test_btn.clicked.connect(self.test_requested.emit)
        self.route_bench_btn.clicked.connect(lambda: self.benchmark_requested.emit(False))
        self.route_bench_all_btn.clicked.connect(lambda: self.benchmark_requested.emit(True))
        for button in (self.route_test_btn, self.route_bench_btn, self.route_bench_all_btn):
            actions.addWidget(button)
        details_form.addRow(actions)

        self.bench_out = QTextEdit()
        self.bench_out.setReadOnly(True)
        self.bench_out.setMinimumHeight(80)
        self.bench_out.setMaximumHeight(150)
        self.bench_out.setLayoutDirection(Qt.LeftToRight)
        details_form.addRow(self.bench_out)

        self.route_enabled_chk.toggled.connect(lambda *_: self.details_changed.emit())
        for widget in (self.route_timeout, self.route_cooldown, self.route_ctx, self.route_predict):
            widget.valueChanged.connect(lambda *_: self.details_changed.emit())
        self.route_model_edit.lineEdit().editingFinished.connect(self.details_changed.emit)
        self.route_model_edit.activated.connect(lambda *_: self.details_changed.emit())

        root.addWidget(route_box)
        root.addWidget(details_box)
