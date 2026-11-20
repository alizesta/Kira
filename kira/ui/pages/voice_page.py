"""Standalone local speech controls page.

The page owns its widgets, layout, translation refresh and debounce timer. It
emits intent signals; the application controller supplies device discovery,
model installation and persistence actions.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSizePolicy,
    QWidget,
)
from ..components.switch_checkbox import SwitchCheckBox


class VoicePage(QScrollArea):
    voice_enabled_requested = Signal(bool)
    choose_whisper_folder_requested = Signal()
    download_whisper_requested = Signal()
    autosave_requested = Signal()

    def __init__(self, settings: dict, translate: Callable[[str], str], parent=None) -> None:
        super().__init__(parent)
        self._translate = translate
        self._translations: list[tuple[Callable[[str], None], str]] = []
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        settings = settings or {}
        mic_box = QGroupBox("میکروفن")
        mic_form = QFormLayout(mic_box)
        mic_form.setContentsMargins(8, 6, 8, 6)
        mic_form.setHorizontalSpacing(8)
        mic_form.setVerticalSpacing(4)
        self.mic_device = self._row(mic_form, "mic_device", QComboBox())
        self.engine_lbl = self._row(mic_form, "engine", QLabel())
        self.mic_gain = self._row(mic_form, "mic_gain", QSlider(Qt.Horizontal))
        self.mic_gain.setRange(50, 300)
        self.mic_gain.setValue(int(settings.get("mic_gain", 100)))
        self.mic_sens = self._row(mic_form, "mic_sens", QSlider(Qt.Horizontal))
        self.mic_sens.setRange(50, 200)
        self.mic_sens.setValue(int(settings.get("mic_sensitivity", 100)))
        self.barge_chk = SwitchCheckBox()
        self.barge_chk.setChecked(bool(settings.get("barge_in", True)))
        self._register(self.barge_chk.setText, "barge_in")
        mic_form.addRow(self.barge_chk)
        self.wake_timeout = self._row(mic_form, "wake_timeout", QSpinBox())
        self.wake_timeout.setRange(5, 120)
        self.wake_timeout.setValue(int(settings.get("wake_timeout", 30)))

        output_box = QGroupBox("خروجی صدا")
        output_form = QFormLayout(output_box)
        output_form.setContentsMargins(8, 6, 8, 6)
        output_form.setHorizontalSpacing(8)
        output_form.setVerticalSpacing(4)
        self.volume = self._row(output_form, "volume", QSlider(Qt.Horizontal))
        self.volume.setRange(0, 100)
        self.volume.setValue(int(float(settings.get("voice_volume", 0.9)) * 100))
        self.out_device = self._row(output_form, "output_device", QComboBox())

        stt_box = QGroupBox("تشخیص گفتار (STT)")
        stt_form = QFormLayout(stt_box)
        stt_form.setContentsMargins(8, 6, 8, 6)
        stt_form.setHorizontalSpacing(8)
        stt_form.setVerticalSpacing(4)
        self.stt_lang = self._row(stt_form, "stt_lang", QComboBox())
        self.stt_lang.addItems(["fa", "en", "auto"])
        self.stt_lang.setCurrentText(str(settings.get("stt_language") or "fa"))
        self.whisper = self._row(stt_form, "whisper", QComboBox())
        self.whisper.setEditable(True)
        self.whisper.addItems([
            "base",
            "small",
            "medium",
            "large-v3-turbo",
            "large-v3",
            "parseh/whisper-fa-accuracy-ct2",
        ])
        self.whisper.setCurrentText(str(settings.get("whisper_model") or "base"))
        self._register(self.whisper.setToolTip, "whisper_tip")
        self.whisper_browse_btn = QPushButton("انتخاب پوشه مدل")
        self.whisper_browse_btn.clicked.connect(lambda checked=False: self.choose_whisper_folder_requested.emit())
        self.whisper_download_btn = QPushButton("نصب مدل انتخاب‌شده")
        self.whisper_download_btn.clicked.connect(lambda checked=False: self.download_whisper_requested.emit())
        stt_actions = QHBoxLayout()
        stt_actions.addWidget(self.whisper_download_btn)
        stt_actions.addWidget(self.whisper_browse_btn)
        stt_form.addRow(stt_actions)

        live_box = QGroupBox("مکالمه‌ی زنده (Gemini Realtime)")
        live_form = QFormLayout(live_box)
        live_form.setContentsMargins(8, 6, 8, 6)
        live_form.setHorizontalSpacing(8)
        live_form.setVerticalSpacing(4)
        self.voice_engine = QComboBox()
        self.voice_engine.addItem("Gemini Realtime (مسیر اصلی)", "gemini_live")
        self.voice_engine.addItem("STT/TTS محلی", "local")
        self.voice_engine.setCurrentIndex(max(0, self.voice_engine.findData(str(settings.get("voice_engine") or "gemini_live"))))
        live_form.addRow("موتور مکالمه", self.voice_engine)
        self.gemini_provider = QComboBox()
        self.refresh_gemini_providers(settings)
        live_form.addRow("کلید Google API", self.gemini_provider)
        self.gemini_model = QComboBox()
        self.gemini_model.setEditable(True)
        self.gemini_model.addItems([
            "gemini-3.8-live",
            "gemini-3.8-live-extended-thinking",
            "gemini-3.1-flash-live-preview",
        ])
        self.gemini_model.setCurrentText(str(settings.get("gemini_live_model") or "gemini-3.8-live"))
        live_form.addRow("مدل Live", self.gemini_model)
        self.local_fallback_chk = SwitchCheckBox("در صورت خطای Realtime، به STT/TTS محلی برگرد")
        self.local_fallback_chk.setChecked(bool(settings.get("voice_local_fallback", True)))
        live_form.addRow(self.local_fallback_chk)
        self.live_config_note = QLabel()
        self.live_config_note.setWordWrap(True)
        live_form.addRow(self.live_config_note)

        tts_box = QGroupBox("تولید گفتار (TTS)")
        tts_form = QFormLayout(tts_box)
        tts_form.setContentsMargins(8, 6, 8, 6)
        tts_form.setHorizontalSpacing(8)
        tts_form.setVerticalSpacing(4)
        self.speak_chk = SwitchCheckBox()
        self.speak_chk.setChecked(bool(settings.get("speak_replies", True)))
        self.speak_chk.toggled.connect(self.voice_enabled_requested.emit)
        self._register(self.speak_chk.setText, "speak_on")
        tts_form.addRow(self.speak_chk)
        self.stream_chk = SwitchCheckBox("خواندن پیوسته‌ی پاسخ")
        self.stream_chk.setChecked(bool(settings.get("stream_speech", True)))
        tts_form.addRow(self.stream_chk)
        self.rate = QSpinBox()
        self.rate.setRange(-30, 30)
        self.rate.setSuffix(" %")
        self.rate.setValue(int(settings.get("voice_rate", 0)))
        tts_form.addRow("سرعت گفتار محلی", self.rate)
        self.voice_caps_note = QLabel("ورودی و خروجی گفتار فقط با موتورهای محلی اجرا می‌شوند.")
        self.voice_caps_note.setWordWrap(True)
        tts_form.addRow(self.voice_caps_note)
        self.tts_form = tts_form

        host = QWidget()
        grid = QGridLayout(host)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        for box in (mic_box, output_box, stt_box, tts_box, live_box):
            box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            box.setMinimumWidth(0)
        grid.addWidget(mic_box, 0, 0)
        grid.addWidget(output_box, 0, 1)
        grid.addWidget(stt_box, 1, 0)
        grid.addWidget(tts_box, 1, 1)
        grid.addWidget(live_box, 2, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        self.setWidget(host)

        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(400)
        self.save_timer.timeout.connect(self.autosave_requested.emit)
        for widget in (self.volume, self.mic_gain, self.mic_sens, self.rate):
            widget.valueChanged.connect(lambda *_: self.save_timer.start())
        for widget in (self.out_device, self.mic_device, self.stt_lang, self.whisper, self.voice_engine, self.gemini_provider):
            widget.currentIndexChanged.connect(lambda *_: self.save_timer.start())
        self.gemini_model.currentTextChanged.connect(lambda *_: self.save_timer.start())
        self.stream_chk.toggled.connect(lambda *_: self.save_timer.start())
        self.local_fallback_chk.toggled.connect(lambda *_: self.save_timer.start())
        self.retranslate()

    def refresh_gemini_providers(self, settings: dict) -> None:
        """Refresh Google credentials from Connections without silently changing a saved provider."""
        combo = self.gemini_provider
        settings = settings or {}
        providers = []
        for provider_id, provider_cfg in (settings.get("providers") or {}).items():
            if not isinstance(provider_cfg, dict):
                continue
            is_google = (
                provider_cfg.get("service") == "google"
                or "generativelanguage.googleapis.com" in str(provider_cfg.get("base_url") or "")
            )
            if is_google and str(provider_cfg.get("api_key") or "").strip():
                providers.append((str(provider_cfg.get("label") or provider_id), provider_id))

        selected = str(combo.currentData() or settings.get("gemini_live_provider") or "")
        combo.blockSignals(True)
        try:
            combo.clear()
            provider_ids = {provider_id for _label, provider_id in providers}
            if selected and selected not in provider_ids:
                combo.addItem("Provider ذخیره‌شده در Connections پیدا نشد", selected)
            for label, provider_id in providers:
                combo.addItem(label, provider_id)
            if not providers and not selected:
                combo.addItem("ابتدا Google AI Studio را در بخش اتصالات ثبت کن", "")
            index = combo.findData(selected)
            if index < 0 and combo.count():
                index = 0
            if index >= 0:
                combo.setCurrentIndex(index)
        finally:
            combo.blockSignals(False)

    def _register(self, setter: Callable[[str], None], key: str) -> None:
        self._translations.append((setter, key))

    def _row(self, form: QFormLayout, key: str, widget: QWidget):
        label = QLabel()
        self._register(label.setText, key)
        form.addRow(label, widget)
        return widget

    def retranslate(self) -> None:
        for setter, key in self._translations:
            setter(self._translate(key))
