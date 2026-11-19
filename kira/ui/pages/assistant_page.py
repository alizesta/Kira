"""Independent assistant/model settings page.

The page owns its widgets and emits user intent. Provider operations and
application settings persistence remain in the application controller.
"""
from __future__ import annotations

from collections.abc import Callable
import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class AssistantPage(QScrollArea):
    test_connection_requested = Signal()
    load_model_requested = Signal()
    unload_model_requested = Signal()
    speed_test_requested = Signal()

    def __init__(
        self,
        settings: dict,
        translate: Callable[[str], str],
        *,
        model_combo_factory,
        num_ctx: int,
        num_predict: int,
        keep_alive: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._translate = translate
        self._translations: list[tuple[Callable[[str], str], str]] = []
        settings = settings or {}
        self.setWidgetResizable(True)

        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        assistant_box, assistant_form = self._group("g_assistant")
        self.name = self._row(assistant_form, "name", self._line_edit(settings.get("assistant_name", "")))
        self.persona = QTextEdit()
        self.persona.setPlainText(str(settings.get("persona", "")))
        self.persona.setMinimumHeight(110)
        self._row(assistant_form, "persona", self.persona)

        from PySide6.QtWidgets import QCheckBox, QLineEdit
        self.modes_chk = QCheckBox()
        self.modes_chk.setChecked(bool(settings.get("active_modes", True)))
        self._register(self.modes_chk.setText, "active_modes")
        self._register(self.modes_chk.setToolTip, "active_modes_tip")
        assistant_form.addRow(self.modes_chk)
        self.temp = self._row(assistant_form, "temp", QComboBox())
        self.temp.addItems(["0.2", "0.4", "0.7", "0.9", "1.0"])
        raw_temperature = settings.get("temperature", 0.7)
        try:
            temperature = float(raw_temperature)
            if not math.isfinite(temperature):
                raise ValueError("temperature must be finite")
            temperature_text = str(raw_temperature).strip()
        except (TypeError, ValueError):
            temperature_text = "0.7"
        if self.temp.findText(temperature_text) < 0:
            self.temp.addItem(temperature_text)
        self.temp.setCurrentText(temperature_text)

        model_box, model_form = self._group("g_model")
        ollama = (settings.get("providers") or {}).get("ollama", {})
        route_note = QLabel("فعال‌سازی و اولویت Ollama از بخش Route مدیریت می‌شود.")
        route_note.setObjectName("hint")
        route_note.setWordWrap(True)
        model_form.addRow(route_note)

        self.model = self._row(model_form, "model", model_combo_factory(settings.get("model", "")))
        self.url = self._row(model_form, "url", QLineEdit(str(settings.get("ollama_url", ""))))
        self.use_qwen_btn = QPushButton()
        self._register(self.use_qwen_btn.setText, "o_use_qwen")
        self.use_qwen_btn.clicked.connect(lambda: self.model.setText("qwen3.5:4b"))
        model_form.addRow(self.use_qwen_btn)

        self.num_ctx = self._row(model_form, "o_ctx", QSpinBox())
        self.num_ctx.setRange(1024, 32768)
        self.num_ctx.setSingleStep(1024)
        self.num_ctx.setValue(int(num_ctx))
        self.num_predict = self._row(model_form, "o_predict", QSpinBox())
        self.num_predict.setRange(32, 4096)
        self.num_predict.setSingleStep(64)
        self.num_predict.setValue(int(num_predict))
        self.keep_alive = self._row(model_form, "o_keep", QComboBox())
        self.keep_alive.setEditable(True)
        self.keep_alive.addItems(["0", "30s", "2m", "5m", "15m"])
        self.keep_alive.setCurrentText(str(keep_alive))

        keep_hint = QLabel()
        keep_hint.setObjectName("hint")
        keep_hint.setWordWrap(True)
        self._register(keep_hint.setText, "o_keep_hint")
        model_form.addRow(keep_hint)

        self.conn_btn = QPushButton()
        self._register(self.conn_btn.setText, "check_conn")
        self.conn_btn.clicked.connect(self.test_connection_requested.emit)
        self.load_btn = QPushButton()
        self._register(self.load_btn.setText, "o_load")
        self.load_btn.clicked.connect(self.load_model_requested.emit)
        self.unload_btn = QPushButton()
        self._register(self.unload_btn.setText, "o_unload")
        self.unload_btn.clicked.connect(self.unload_model_requested.emit)
        actions = QHBoxLayout()
        actions.addWidget(self.conn_btn)
        actions.addWidget(self.load_btn)
        actions.addWidget(self.unload_btn)
        model_form.addRow(actions)

        self.speed_btn = QPushButton()
        self._register(self.speed_btn.setText, "o_speed")
        self.speed_btn.clicked.connect(self.speed_test_requested.emit)
        model_form.addRow(self.speed_btn)
        self.conn_lbl = QLabel()
        self.conn_lbl.setWordWrap(True)
        model_form.addRow(self.conn_lbl)

        game_note = QLabel()
        game_note.setObjectName("hint")
        game_note.setWordWrap(True)
        self._register(game_note.setText, "o_game_note")
        model_form.addRow(game_note)

        layout.addWidget(assistant_box)
        layout.addWidget(model_box)
        layout.addStretch(1)
        self.setWidget(host)
        self.retranslate()

    @staticmethod
    def _line_edit(value: str):
        from PySide6.QtWidgets import QLineEdit
        return QLineEdit(str(value))

    def _register(self, setter, key: str) -> None:
        self._translations.append((setter, key))

    def _row(self, form: QFormLayout, key: str, widget: QWidget):
        label = QLabel()
        self._register(label.setText, key)
        form.addRow(label, widget)
        return widget

    def _group(self, key: str):
        box = QGroupBox()
        self._register(box.setTitle, key)
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignLeading)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(5)
        return box, form

    def retranslate(self) -> None:
        for setter, key in self._translations:
            setter(self._translate(key))
