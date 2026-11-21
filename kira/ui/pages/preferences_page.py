"""Independent preferences page for language, web research and memory actions.

The widget owns presentation only. Side effects are emitted as intent signals
and handled by the application controller.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable

from PySide6.QtCore import Qt, Signal
from kira.ui.pages._all_pages_fluid_finalizers import finalize_preferences_page

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from ..components.switch_checkbox import SwitchCheckBox


class PreferencesPage(QScrollArea):
    web_search_test_requested = Signal()
    clear_history_requested = Signal()
    restore_history_requested = Signal()
    open_memory_requested = Signal()
    import_history_requested = Signal()
    ui_design_guidance_changed = Signal(bool)

    def __init__(
        self,
        settings: dict,
        translate: Callable[[str], str],
        *,
        web_depths: Iterable[tuple[str, str]],
        about_rows: Iterable[tuple[str, str]],
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

        language_box, language_form = self._group("g_lang")
        self.ui_lang = self._row(language_form, "ui_lang", QComboBox())
        self.ui_lang.addItem("فارسی", "fa")
        self.ui_lang.addItem("English", "en")
        self.ui_lang.setCurrentIndex(0 if settings.get("ui_lang", "fa") == "fa" else 1)

        self.tavily_key = QLineEdit(str(settings.get("tavily_api_key", "")))
        self.tavily_key.setEchoMode(QLineEdit.Password)
        self.tavily_key.setPlaceholderText("tvly-…  (رایگان از tavily.com)")
        self.tavily_key.setLayoutDirection(Qt.LeftToRight)
        language_form.addRow("کلید جست‌وجوی وب (Tavily)", self.tavily_key)

        self.web_depth = QComboBox()
        for value, label in web_depths:
            self.web_depth.addItem(label, value)
        self.web_depth.setCurrentIndex(
            max(0, self.web_depth.findData(settings.get("web_depth", "basic")))
        )
        self.web_depth.setToolTip(
            "«دقیق» دو برابر اعتبار مصرف می‌کند ولی برای چیزهای سخت مثل نام آهنگ و خواننده بهتر است."
        )
        language_form.addRow("عمق جست‌وجو", self.web_depth)

        self.web_fallback_chk = SwitchCheckBox(
            "اگر Tavily کار نکرد، با Google (Gemini) و بعد DuckDuckGo جست‌وجو کن"
        )
        self.web_fallback_chk.setChecked(bool(settings.get("web_fallback", True)))
        language_form.addRow(self.web_fallback_chk)
        self.web_test_btn = QPushButton("آزمایش جست‌وجوی وب")
        self.web_test_btn.clicked.connect(self.web_search_test_requested.emit)
        language_form.addRow("", self.web_test_btn)

        design_box, design_form = self._group("راهنمای طراحی رابط")
        self.ui_design_guidance_chk = SwitchCheckBox("Appllama و ممیزی شش‌گانهٔ Unslop برای طراحی رابط کیرا و Kode")
        self.ui_design_guidance_chk.setChecked(bool(settings.get("ui_design_guidance_enabled", True)))
        self.ui_design_guidance_chk.toggled.connect(self.ui_design_guidance_changed.emit)
        design_form.addRow(self.ui_design_guidance_chk)

        memory_box, memory_form = self._group("g_memory")
        clear_button = QPushButton()
        self._register(clear_button.setText, "clear_mem")
        clear_button.clicked.connect(self.clear_history_requested.emit)
        memory_form.addRow(clear_button)
        self.restore_chat_btn = QPushButton("بازگرداندن آخرین پاک‌سازی")
        self.restore_chat_btn.clicked.connect(self.restore_history_requested.emit)
        memory_form.addRow(self.restore_chat_btn)
        self.memory_btn = QPushButton("حافظه‌ی Kira درباره‌ی تو: مشاهده، ویرایش و حذف…")
        self.memory_btn.clicked.connect(self.open_memory_requested.emit)
        memory_form.addRow(self.memory_btn)
        self.import_chat_btn = QPushButton("ورود گفتگو از نسخه‌ی قدیمی…")
        self.import_chat_btn.clicked.connect(self.import_history_requested.emit)
        memory_form.addRow(self.import_chat_btn)

        about_box, about_form = self._group("g_about")
        self.about_labels = {}
        for key, value in about_rows:
            label = QLabel(str(value))
            label.setObjectName(str(key))
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.about_labels[key] = self._row(about_form, key, label)

        layout.addWidget(language_box)
        layout.addWidget(design_box)
        layout.addWidget(memory_box)
        layout.addWidget(about_box)
        layout.addStretch(1)
        self.setWidget(host)
        self.retranslate()

        finalize_preferences_page(self)

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
