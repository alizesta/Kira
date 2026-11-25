"""Independent appearance controls page; theme application remains an app service."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from kira.ui.pages._all_pages_fluid_finalizers import finalize_appearance_page
from kira.settings_schema import (
    DEFAULTS as SETTINGS_DEFAULTS,
    SETTING_RANGES as SETTINGS_RANGES,
)

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class AppearancePage(QScrollArea):
    """Own appearance controls and emit changes without importing the application window."""

    appearance_apply_requested = Signal(bool)
    choose_color_requested = Signal()
    reset_requested = Signal()

    DEFAULTS = SETTINGS_DEFAULTS["appearance"]

    def __init__(
        self,
        settings: dict,
        translate: Callable[[str], str],
        *,
        glass_supported: bool,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._translate = translate
        self._translations: list[tuple[Callable[[str], None], str]] = []
        settings = settings or {}
        appearance = {**self.DEFAULTS, **(settings.get("appearance") or {})}
        self._background_color = str(appearance["background_color"] or self.DEFAULTS["background_color"])

        self.setWidgetResizable(True)
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        box = QGroupBox("ظاهر برنامه")
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignLeading)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(5)

        self.window_effect = QComboBox()
        for label, value in (
            ("شیشه‌ای (Acrylic)", "acrylic"),
            ("شیشه‌ای ملایم (Mica)", "mica"),
            ("ساده", "off"),
        ):
            self.window_effect.addItem(label, value)
        self.window_effect.setCurrentIndex(
            max(0, self.window_effect.findData(settings.get("window_effect", SETTINGS_DEFAULTS["window_effect"])))
        )
        if not glass_supported:
            self.window_effect.setEnabled(False)
            self.window_effect.setToolTip(
                "حالت شیشه‌ای فقط روی Windows 11 (نسخه‌ی 22H2 به بالا) کار می‌کند."
            )
        form.addRow("حالت پنجره", self.window_effect)

        colour_row = QHBoxLayout()
        self.appearance_color_btn = QPushButton("انتخاب رنگ پس‌زمینه")
        self.appearance_color_preview = QLabel(self._background_color)
        self.appearance_color_preview.setMinimumWidth(92)
        self.appearance_color_preview.setAlignment(Qt.AlignCenter)
        self.appearance_color_btn.clicked.connect(lambda checked=False: self.choose_color_requested.emit())
        colour_row.addWidget(self.appearance_color_btn)
        colour_row.addWidget(self.appearance_color_preview)
        form.addRow("رنگ پس‌زمینه", colour_row)
        self._set_color_preview(self._background_color)

        brightness_min, brightness_max = SETTINGS_RANGES["appearance.brightness"]
        self.appearance_brightness = self._slider(
            form, "روشنایی", brightness_min, brightness_max, appearance["brightness"]
        )
        self.appearance_brightness.setToolTip(
            "روشنایی رنگ‌های پس‌زمینه را تنظیم می‌کند؛ مقدار بیشتر یعنی روشن‌تر."
        )
        glow_min, glow_max = SETTINGS_RANGES["appearance.glow"]
        self.appearance_glow = self._slider(
            form, "درخشش نور", glow_min, glow_max, appearance["glow"]
        )
        self.appearance_glow.setToolTip(
            "درخشش آیکون‌ها، حاشیه‌ها و سایه‌ی کارت گفتگو را کنترل می‌کند."
        )
        transparency_min, transparency_max = SETTINGS_RANGES["appearance.transparency"]
        self.appearance_transparency = self._slider(
            form, "شفافیت", transparency_min, transparency_max, appearance["transparency"]
        )
        self.appearance_transparency.setToolTip(
            "مقدار بیشتر، سطح پنجره را شفاف‌تر می‌کند."
        )

        reset = QPushButton("بازنشانی ظاهر")
        reset.clicked.connect(lambda checked=False: self.reset_requested.emit())
        form.addRow(reset)
        hint = QLabel(
            "تغییرات فوراً پیش‌نمایش می‌شوند و خودکار ذخیره می‌شوند. برای Acrylic و Mica به Windows 11 نیاز است."
        )
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        form.addRow(hint)
        layout.addWidget(box)
        layout.addStretch(1)
        self.setWidget(host)

        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(160)
        self.save_timer.timeout.connect(lambda: self.appearance_apply_requested.emit(True))
        self.window_effect.currentIndexChanged.connect(self.schedule_appearance)
        for slider in (
            self.appearance_brightness,
            self.appearance_glow,
            self.appearance_transparency,
        ):
            slider.valueChanged.connect(self.schedule_appearance)

        finalize_appearance_page(self)

    def _slider(self, form: QFormLayout, key: str, minimum: int, maximum: int, value: int):
        label = QLabel()
        self._translations.append((label.setText, key))
        slider = QSlider(Qt.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(int(value))
        form.addRow(label, slider)
        return slider

    @property
    def background_color(self) -> str:
        return self._background_color

    def set_background_color(self, value: str) -> None:
        self._background_color = str(value or self.DEFAULTS["background_color"])
        self._set_color_preview(self._background_color)

    def _set_color_preview(self, value: str) -> None:
        colour = str(value or self.DEFAULTS["background_color"])
        self.appearance_color_preview.setText(colour)
        self.appearance_color_preview.setStyleSheet(
            f"QLabel {{ background: {colour}; border: 1px solid rgba(255,255,255,0.35); "
            "border-radius: 7px; padding: 5px; color: white; }"
        )

    def schedule_appearance(self, *_args) -> None:
        self.save_timer.start()

    def retranslate(self) -> None:
        for setter, key in self._translations:
            setter(self._translate(key))
