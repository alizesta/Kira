"""Voice controls page for Gemini Live, local STT/TTS and audio devices.

The page owns its widgets, layout, translation refresh and debounce timer. It
emits intent signals; the application controller supplies session lifecycle,
device discovery, model installation and persistence actions.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from kira.ui.pages._all_pages_fluid_finalizers import finalize_voice_page

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from ..components.switch_checkbox import SwitchCheckBox
from kira.settings_schema import (
    DEFAULTS as SETTINGS_DEFAULTS,
    SETTING_RANGES as SETTINGS_RANGES,
    STT_LANGUAGE_OPTIONS as SETTINGS_STT_LANGUAGE_OPTIONS,
)


# Gemini Live prebuilt voices: (API name, label shown to the user)
GEMINI_VOICES = (
    ("Zephyr", "Zephyr · زن، روشن (پیش‌فرض)"),
    ("Kore", "Kore · زن، محکم"),
    ("Leda", "Leda · زن، جوان"),
    ("Aoede", "Aoede · زن، آرام"),
    ("Puck", "Puck · مرد، شاد"),
    ("Charon", "Charon · مرد، آرام"),
    ("Fenrir", "Fenrir · مرد، پرانرژی"),
    ("Orus", "Orus · مرد، محکم"),
)


class VoicePage(QScrollArea):
    voice_enabled_requested = Signal(bool)
    autosave_requested = Signal()
    live_requested = Signal(bool)
    download_shenava_requested = Signal()
    test_shenava_file_requested = Signal()
    realtime_asr_requested = Signal(bool)
    local_asr_enabled_requested = Signal(bool)
    local_tts_enabled_requested = Signal(bool)
    download_piper_requested = Signal()
    test_piper_requested = Signal()
    choose_piper_file_requested = Signal()
    select_piper_requested = Signal(str)
    test_kitten_requested = Signal(str)

    def __init__(self, settings: dict, translate: Callable[[str], str], parent=None, asr_catalog=None) -> None:
        super().__init__(parent)
        self._translate = translate
        self._translations: list[tuple[Callable[[str], None], str]] = []
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        settings = {**SETTINGS_DEFAULTS, **(settings or {})}
        self._settings = settings
        mic_box = QGroupBox("میکروفن")
        mic_form = QFormLayout(mic_box)
        mic_form.setContentsMargins(8, 6, 8, 6)
        mic_form.setHorizontalSpacing(8)
        mic_form.setVerticalSpacing(4)
        self.mic_device = self._row(mic_form, "mic_device", QComboBox())
        self.engine_lbl = self._row(mic_form, "engine", QLabel())
        self.mic_gain = self._row(mic_form, "mic_gain", QSlider(Qt.Horizontal))
        self.mic_gain.setRange(*SETTINGS_RANGES["mic_gain"])
        self.mic_gain.setValue(int(settings.get("mic_gain", SETTINGS_DEFAULTS["mic_gain"])))
        self.mic_sens = self._row(mic_form, "mic_sens", QSlider(Qt.Horizontal))
        self.mic_sens.setRange(*SETTINGS_RANGES["mic_sensitivity"])
        self.mic_sens.setValue(int(settings.get("mic_sensitivity", SETTINGS_DEFAULTS["mic_sensitivity"])))
        self.barge_chk = SwitchCheckBox()
        self.barge_chk.setChecked(bool(settings.get("barge_in", SETTINGS_DEFAULTS["barge_in"])))
        self._register(self.barge_chk.setText, "barge_in")
        mic_form.addRow(self.barge_chk)
        self.wake_timeout = self._row(mic_form, "wake_timeout", QSpinBox())
        self.wake_timeout.setRange(*SETTINGS_RANGES["wake_timeout"])
        self.wake_timeout.setValue(int(settings.get("wake_timeout", SETTINGS_DEFAULTS["wake_timeout"])))
        self.real_time_asr_chk = SwitchCheckBox(
            "تشخیص زنده با میکروفن (Real-time ASR)"
        )
        self.real_time_asr_chk.setChecked(bool(settings.get("realtime_asr_enabled", SETTINGS_DEFAULTS["realtime_asr_enabled"])))
        self.real_time_asr_chk.setToolTip(
            "این گزینه فقط میکروفن STT محلی و حالت بیدارباش را کنترل می‌کند؛ "
            "آزمایش آفلاین فایل WAV فعال می‌ماند و Gemini Live مستقل است."
        )
        self.real_time_asr_chk.toggled.connect(self.realtime_asr_requested.emit)
        mic_form.addRow(self.real_time_asr_chk)

        output_box = QGroupBox("خروجی صدا")
        output_form = QFormLayout(output_box)
        output_form.setContentsMargins(8, 6, 8, 6)
        output_form.setHorizontalSpacing(8)
        output_form.setVerticalSpacing(4)
        self.volume = self._row(output_form, "volume", QSlider(Qt.Horizontal))
        volume_min, volume_max = SETTINGS_RANGES["voice_volume"]
        self.volume.setRange(round(volume_min * 100), round(volume_max * 100))
        self.volume.setValue(int(float(settings.get("voice_volume", SETTINGS_DEFAULTS["voice_volume"])) * 100))
        self.out_device = self._row(output_form, "output_device", QComboBox())

        stt_box = QGroupBox("تشخیص گفتار (STT)")
        stt_form = QFormLayout(stt_box)
        stt_form.setContentsMargins(8, 6, 8, 6)
        stt_form.setHorizontalSpacing(8)
        stt_form.setVerticalSpacing(4)
        self.stt_lang = self._row(stt_form, "stt_lang", QComboBox())
        self.stt_lang.addItems(SETTINGS_STT_LANGUAGE_OPTIONS)
        self.stt_lang.setCurrentText(str(settings.get("stt_language") or SETTINGS_DEFAULTS["stt_language"]))
        selected_asr_engine = str(settings.get("local_voice_asr_backend") or SETTINGS_DEFAULTS["local_voice_asr_backend"]).strip().lower()
        selected_asr_model = str(settings.get("local_voice_asr_model") or SETTINGS_DEFAULTS["local_voice_asr_model"])
        self._asr_catalog = {
            str(item.get("id") or "").strip().lower(): dict(item)
            for item in (asr_catalog or [])
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        }
        self.asr_backend = QComboBox()
        for engine_id, item in self._asr_catalog.items():
            self.asr_backend.addItem(str(item.get("label") or item.get("name") or engine_id), engine_id)
        if selected_asr_engine not in self._asr_catalog:
            self.asr_backend.addItem(
                f"موتور ذخیره‌شده پشتیبانی نمی‌شود: {selected_asr_engine or 'unknown'}",
                selected_asr_engine,
            )
        engine_index = self.asr_backend.findData(selected_asr_engine)
        self.asr_backend.setCurrentIndex(engine_index if engine_index >= 0 else 0)
        stt_form.addRow("موتور ASR", self.asr_backend)

        self.asr_model = QComboBox()
        self.shenava_variant = self.asr_model  # compatibility for existing integrations
        self._populate_asr_models(selected_asr_engine, selected_asr_model)
        stt_form.addRow("مدل ASR", self.asr_model)
        self.asr_backend.currentIndexChanged.connect(self._on_asr_engine_changed)
        self.asr_model.currentIndexChanged.connect(lambda *_: self._update_shenava_download_label())

        self.local_asr_chk = SwitchCheckBox("استفاده از موتور تشخیص گفتار محلی")
        self.local_asr_chk.setChecked(bool(settings.get("local_voice_asr", SETTINGS_DEFAULTS["local_voice_asr"])))
        self.local_asr_chk.toggled.connect(self.local_asr_enabled_requested.emit)
        stt_form.addRow(self.local_asr_chk)
        shenava_actions = QGridLayout()
        shenava_actions.setHorizontalSpacing(8)
        shenava_actions.setVerticalSpacing(6)
        self.shenava_download_btn = QPushButton()
        self.shenava_download_btn.clicked.connect(
            lambda checked=False: self.download_shenava_requested.emit()
        )
        self._update_shenava_download_label()
        self.shenava_test_btn = QPushButton("تست ASR با فایل WAV")
        self.shenava_test_btn.clicked.connect(
            lambda checked=False: self.test_shenava_file_requested.emit()
        )
        self._responsive_action_groups = []
        self._responsive_action_columns = []
        self._responsive_action_groups.append(
            (shenava_actions, (self.shenava_download_btn, self.shenava_test_btn))
        )
        stt_form.addRow(shenava_actions)
        self.shenava_result = QLabel(
            "وضعیت موتور و مدل انتخاب‌شده از ASR Manager خوانده می‌شود. "
            "مدل تا زمان تأیید Runtime و فایل‌های واقعی آماده محسوب نمی‌شود."
        )
        self.asr_result = self.shenava_result
        self.shenava_result.setWordWrap(True)
        self.shenava_result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        stt_form.addRow(self.shenava_result)

        live_box = QGroupBox("مکالمه صوتی زنده · Gemini Live")
        live_form = QFormLayout(live_box)
        live_form.setContentsMargins(8, 6, 8, 6)
        live_form.setHorizontalSpacing(8)
        live_form.setVerticalSpacing(4)
        # Gemini Live is the primary bidirectional audio path; local STT/TTS is a fallback.
        self.live_toggle = QPushButton("شروع مکالمه صوتی Gemini")
        self.live_toggle.setCheckable(True)
        self.live_toggle.toggled.connect(
            lambda enabled: (
                self._update_live_toggle_text(bool(enabled)),
                self.live_requested.emit(bool(enabled)),
            )
        )
        live_form.addRow(self.live_toggle)
        self.voice_engine = QComboBox()
        self.voice_engine.addItem("ریل‌تایم · Gemini Live", "gemini_live")
        self.voice_engine.addItem("محلی · آفلاین", "local")
        selected_engine = str(settings.get("voice_engine") or SETTINGS_DEFAULTS["voice_engine"])
        self.voice_engine.setCurrentIndex(max(0, self.voice_engine.findData(selected_engine)))
        live_form.addRow("موتور اصلی", self.voice_engine)
        self.gemini_provider = QComboBox()
        self.refresh_gemini_providers(settings)
        live_form.addRow("کلید Google AI", self.gemini_provider)
        self.gemini_refresh_btn = QPushButton("تازه‌سازی اتصال‌های Google")
        self.gemini_refresh_btn.clicked.connect(
            lambda checked=False: self.refresh_gemini_providers(self._settings)
        )
        live_form.addRow(self.gemini_refresh_btn)
        self.gemini_model = QComboBox()
        self.gemini_model.setEditable(True)
        self.gemini_model.addItems([
            "gemini-3.8-live",
            "gemini-3.8-live-extended-thinking",
        ])
        self.gemini_model.setCurrentText(str(settings.get("gemini_live_model") or SETTINGS_DEFAULTS["gemini_live_model"]))
        self.gemini_model.setEnabled(True)
        live_form.addRow("مدل Gemini Live", self.gemini_model)
        self.gemini_voice = QComboBox()
        for voice_name, voice_label in GEMINI_VOICES:
            self.gemini_voice.addItem(voice_label, voice_name)
        self.gemini_voice.setCurrentIndex(max(0, self.gemini_voice.findData(str(settings.get("gemini_voice") or SETTINGS_DEFAULTS["gemini_voice"]))))
        self.gemini_voice.currentIndexChanged.connect(lambda *_: self.autosave_requested.emit())
        self.local_fallback_chk = SwitchCheckBox("در صورت قطع Gemini Live، انتقال خودکار به STT/TTS محلی")
        self.local_fallback_chk.setChecked(bool(settings.get("voice_local_fallback", SETTINGS_DEFAULTS["voice_local_fallback"])))
        live_form.addRow(self.local_fallback_chk)
        self.live_config_note = QLabel()
        self.live_config_note.setWordWrap(True)
        self.live_config_note.setText(
            "حالت اصلی Gemini Live است: صدای میکروفن مستقیم ارسال و پاسخ صوتی مستقیم دریافت می‌شود. "
            "در صورت قطع اتصال، اگر گزینه پشتیبان فعال باشد، Kira به STT محلی "
            "شنوا + مدل چت + Piper منتقل می‌شود. "
            "Real-time ASR فقط میکروفن محلی را کنترل می‌کند و روی Gemini Live اثری ندارد."
        )
        live_form.addRow(self.live_config_note)

        tts_box = QGroupBox("تولید گفتار (TTS)")
        tts_form = QFormLayout(tts_box)
        tts_form.setContentsMargins(8, 6, 8, 6)
        tts_form.setHorizontalSpacing(8)
        tts_form.setVerticalSpacing(4)
        self.speak_chk = SwitchCheckBox()
        self.speak_chk.setChecked(bool(settings.get("speak_replies", SETTINGS_DEFAULTS["speak_replies"])))
        self.speak_chk.toggled.connect(self.voice_enabled_requested.emit)
        self._register(self.speak_chk.setText, "speak_on")
        tts_form.addRow(self.speak_chk)
        self.stream_chk = SwitchCheckBox("خواندن پیوسته‌ی پاسخ")
        self.stream_chk.setChecked(bool(settings.get("stream_speech", SETTINGS_DEFAULTS["stream_speech"])))
        tts_form.addRow(self.stream_chk)
        self.local_tts_chk = SwitchCheckBox("استفاده از Piper محلی")
        self.local_tts_chk.setChecked(bool(settings.get("local_voice_tts", SETTINGS_DEFAULTS["local_voice_tts"])))
        self.local_tts_chk.toggled.connect(self.local_tts_enabled_requested.emit)
        tts_form.addRow(self.local_tts_chk)
        self.local_tts_model = QComboBox()
        self.local_tts_model.setToolTip("صدای فارسی پیش‌فرض یا صداهای Piper نصب‌شده")
        self.local_tts_model.addItem("Mana Persian Piper · صدای پیش‌فرض", "")
        self.local_tts_model.currentIndexChanged.connect(
            lambda index: self.select_piper_requested.emit(str(self.local_tts_model.itemData(index) or ""))
        )
        tts_form.addRow("صدای Piper", self.local_tts_model)
        piper_actions = QGridLayout()
        piper_actions.setHorizontalSpacing(8)
        piper_actions.setVerticalSpacing(6)
        self.piper_download_btn = QPushButton("دانلود صدای Piper")
        self.piper_download_btn.clicked.connect(lambda checked=False: self.download_piper_requested.emit())
        self.piper_file_btn = QPushButton("انتخاب ONNX")
        self.piper_file_btn.clicked.connect(lambda checked=False: self.choose_piper_file_requested.emit())
        self.piper_test_btn = QPushButton("تست صدا")
        self.piper_test_btn.clicked.connect(lambda checked=False: self.test_piper_requested.emit())
        self._responsive_action_groups.append(
            (piper_actions, (self.piper_download_btn, self.piper_file_btn, self.piper_test_btn))
        )
        tts_form.addRow(piper_actions)
        self.tts_engine = QComboBox()
        self.tts_engine.addItem("Piper · فارسی (پیش‌فرض)", "piper")
        self.tts_engine.addItem("KittenTTS · انگلیسی، سریع و سبک", "kitten")
        self.tts_engine.setToolTip("موتور ساخت صدای کیرا. جمله‌های فارسی همیشه با Piper خوانده می‌شوند؛ Kitten فقط انگلیسی می‌خواند.")
        saved_engine = str(settings.get("tts_engine") or SETTINGS_DEFAULTS["tts_engine"]).lower()
        self.tts_engine.setCurrentIndex(max(0, self.tts_engine.findData(saved_engine)))
        self.tts_engine.currentIndexChanged.connect(lambda *_: self.autosave_requested.emit())
        tts_form.addRow("موتور صدا", self.tts_engine)
        self.kitten_model = QComboBox()
        self.kitten_model.addItem("Kitten 2 Pico · INT4 · 4 MB", "pico")
        self.kitten_model.addItem("Kitten 2 Nano · INT4 · 8.8 MB", "nano")
        self.kitten_model.addItem("Kitten 2 Mini · INT4 · 47.5 MB", "mini")
        self.kitten_model.setCurrentIndex(max(0, self.kitten_model.findData(str(settings.get("kitten_model") or SETTINGS_DEFAULTS["kitten_model"]).lower())))
        self.kitten_model.currentIndexChanged.connect(lambda *_: self.autosave_requested.emit())
        tts_form.addRow("مدل KittenTTS", self.kitten_model)
        self.kitten_test_btn = QPushButton("نصب و تست KittenTTS")
        self.kitten_test_btn.setToolTip("مدل انتخابی را دانلود می‌کند و یک نمونه انگلیسی را با صدای آن پخش می‌کند.")
        self.kitten_test_btn.clicked.connect(
            lambda checked=False: self.test_kitten_requested.emit(str(self.kitten_model.currentData() or SETTINGS_DEFAULTS["kitten_model"]))
        )
        tts_form.addRow(self.kitten_test_btn)
        self.kitten_result = QLabel("KittenTTS فقط انگلیسی می‌خواند؛ جمله‌های فارسی خودکار با Piper خوانده می‌شوند. اول «نصب و تست» را بزن، بعد موتور را روی Kitten بگذار.")
        self.kitten_result.setWordWrap(True)
        self.kitten_result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        tts_form.addRow(self.kitten_result)
        self.rate = QSpinBox()
        self.rate.setRange(*SETTINGS_RANGES["voice_rate"])
        self.rate.setSuffix(" %")
        self.rate.setValue(int(settings.get("voice_rate", SETTINGS_DEFAULTS["voice_rate"])))
        tts_form.addRow("سرعت گفتار محلی", self.rate)
        self.local_voice_status = QLabel()
        self.local_voice_status.setWordWrap(True)
        self.local_voice_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.local_voice_status.setObjectName("hint")
        tts_form.addRow(self.local_voice_status)
        self.voice_caps_note = QLabel("Gemini Live مکالمه صوتی مستقیم را انجام می‌دهد؛ STT/TTS محلی فقط مسیر پشتیبان است.")
        self.voice_caps_note.setWordWrap(True)
        tts_form.addRow(self.voice_caps_note)
        self.tts_form = tts_form

        # ---- simple top card: the conversation mode and only the fields that matter for it ----
        def lift(form, field):
            """Move one row out of its old form; returns the label widget it had (or None)."""
            row = form.takeRow(field)
            return row.labelItem.widget() if row.labelItem is not None else None

        mode_box = QGroupBox("مکالمه")
        mode_form = QFormLayout(mode_box)
        mode_form.setContentsMargins(8, 6, 8, 6)
        mode_form.setHorizontalSpacing(8)
        mode_form.setVerticalSpacing(6)
        mode_label = lift(live_form, self.voice_engine)
        mode_form.addRow("نوع مکالمه", self.voice_engine)
        if mode_label is not None:
            mode_label.hide()
            mode_label.deleteLater()
        lift(live_form, self.live_toggle)
        mode_form.addRow(self.live_toggle)

        # realtime (Gemini Live): key + voice. What the user says is written into the chat.
        self._realtime_group = QWidget()
        realtime_form = QFormLayout(self._realtime_group)
        realtime_form.setContentsMargins(0, 0, 0, 0)
        realtime_form.setVerticalSpacing(6)
        for field, text in ((self.gemini_provider, "کلید Google AI"),):
            old = lift(live_form, field)
            realtime_form.addRow(text, field)
            if old is not None:
                old.hide()
                old.deleteLater()
        realtime_form.addRow("صدای کیرا", self.gemini_voice)
        realtime_hint = QLabel("حرف‌های تو و پاسخ کیرا بعد از هر نوبت در چت نوشته می‌شود.")
        realtime_hint.setObjectName("hint")
        realtime_hint.setWordWrap(True)
        realtime_form.addRow(realtime_hint)
        mode_form.addRow(self._realtime_group)

        # local (offline): input = Shenava (automatic), output = the TTS engine
        self._local_group = QWidget()
        local_form = QFormLayout(self._local_group)
        local_form.setContentsMargins(0, 0, 0, 0)
        local_form.setVerticalSpacing(6)
        stt_value = QLabel()
        self.asr_engine_label = stt_value
        local_form.addRow("ورودی (STT)", stt_value)
        old = lift(tts_form, self.tts_engine)
        local_form.addRow("خروجی (TTS)", self.tts_engine)
        if old is not None:
            old.hide()
            old.deleteLater()
        local_hint = QLabel("جمله‌های فارسی همیشه با Piper خوانده می‌شوند؛ Kitten فقط انگلیسی می‌خواند.")
        local_hint.setObjectName("hint")
        local_hint.setWordWrap(True)
        local_form.addRow(local_hint)
        mode_form.addRow(self._local_group)

        # speaking on/off belongs with the output card
        lift(tts_form, self.speak_chk)
        output_form.insertRow(0, self.speak_chk)

        # ---- everything else lives in one collapsed "advanced" area ----
        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setObjectName("advancedToggle")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.advanced_toggle.setArrowType(Qt.RightArrow)
        self.advanced_toggle.setText("تنظیمات پیشرفته")
        self.advanced_toggle.setCursor(Qt.PointingHandCursor)
        advanced_body = QWidget()
        grid = QGridLayout(advanced_body)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        for box in (mic_box, output_box, stt_box, tts_box, live_box):
            box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            box.setMinimumWidth(0)
        self._sections_grid = grid
        self._voice_sections = (mic_box, output_box, stt_box, tts_box, live_box)
        self._responsive_columns = 0
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self._advanced_sections = (stt_box, tts_box, live_box)      # mic + output stay visible; the rest is "advanced"
        for box in self._advanced_sections:
            box.setVisible(False)
        self.advanced_toggle.setStyleSheet("QToolButton,QToolButton:checked,QToolButton:hover{background:rgba(24,32,64,0.62);color:#ffffff;border:1px solid rgba(143,107,255,0.55);border-radius:10px;font-weight:700;padding:5px 14px;}")
        self.advanced_toggle.toggled.connect(self._toggle_advanced)

        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(6, 6, 6, 6)
        host_layout.setSpacing(8)
        host_layout.addWidget(mode_box)
        host_layout.addWidget(self.advanced_toggle, 0, Qt.AlignLeft)
        host_layout.addWidget(advanced_body)
        host_layout.addStretch(1)
        self.setWidget(host)
        self.voice_engine.currentIndexChanged.connect(lambda *_: self._sync_mode_groups())
        self._sync_mode_groups()

        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(400)
        self.save_timer.timeout.connect(self.autosave_requested.emit)
        for widget in (self.volume, self.mic_gain, self.mic_sens, self.rate):
            widget.valueChanged.connect(lambda *_: self.save_timer.start())
        for widget in (
            self.out_device, self.mic_device, self.stt_lang,
            self.shenava_variant, self.voice_engine, self.gemini_provider, self.gemini_voice,
        ):
            widget.currentIndexChanged.connect(lambda *_: self.save_timer.start())
        self.gemini_model.currentTextChanged.connect(lambda *_: self.save_timer.start())
        self.voice_engine.currentIndexChanged.connect(lambda *_: self._update_live_toggle_text())
        self.stream_chk.toggled.connect(lambda *_: self.save_timer.start())
        self.local_fallback_chk.toggled.connect(lambda *_: self.save_timer.start())
        self.real_time_asr_chk.toggled.connect(lambda *_: self.save_timer.start())
        self._update_live_toggle_text(False)
        self.retranslate()

        finalize_voice_page(self)
        QTimer.singleShot(0, self._reflow_sections)

    def _sync_mode_groups(self) -> None:
        """Show only the fields of the chosen conversation mode."""
        local = self.voice_engine.currentData() == "local"
        self._realtime_group.setVisible(not local)
        self._local_group.setVisible(local)
        self._update_asr_engine_label()

    def _toggle_advanced(self, on: bool) -> None:
        for box in self._advanced_sections:
            box.setVisible(bool(on))
        self.advanced_toggle.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        QTimer.singleShot(0, self._reflow_sections)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reflow_sections()

    def refresh_responsive_layout(self) -> None:
        """Recalculate card and action layouts after controls or forms change."""
        self._responsive_columns = 0
        self._reflow_sections()

    def _reflow_sections(self) -> None:
        grid = getattr(self, "_sections_grid", None)
        sections = list(getattr(self, "_voice_sections", ()))
        viewport_width = self.viewport().width()
        if grid is None or len(sections) != 5 or viewport_width <= 0:
            return

        # The preferred content width is the breakpoint; no fixed widget width is imposed.
        column_width = max((section.sizeHint().width() for section in sections[:4]), default=0)
        margins = grid.contentsMargins()
        required_width = (column_width * 2) + grid.horizontalSpacing() + margins.left() + margins.right()
        columns = 2 if viewport_width >= required_width else 1

        if columns != self._responsive_columns:
            for widget in sections:
                grid.removeWidget(widget)
            if columns == 2:
                grid.addWidget(sections[0], 0, 0)
                grid.addWidget(sections[1], 0, 1)
                grid.addWidget(sections[2], 1, 0)
                grid.addWidget(sections[3], 1, 1)
                grid.addWidget(sections[4], 2, 0, 1, 2)
            else:
                for row, widget in enumerate(sections):
                    grid.addWidget(widget, row, 0, 1, 1)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1 if columns == 2 else 0)
            grid.setColumnMinimumWidth(0, 0)
            grid.setColumnMinimumWidth(1, 0)
            self._responsive_columns = columns

        panel_width = max(1, viewport_width // columns)
        for index, (layout, buttons) in enumerate(self._responsive_action_groups):
            preferred = [button.sizeHint().width() for button in buttons]
            gap = max(0, layout.horizontalSpacing())
            if sum(preferred) + gap * (len(buttons) - 1) <= panel_width:
                action_columns = len(buttons)
            elif len(buttons) > 1 and sum(sorted(preferred, reverse=True)[:2]) + gap <= panel_width:
                action_columns = 2
            else:
                action_columns = 1

            previous = self._responsive_action_columns[index] if index < len(self._responsive_action_columns) else 0
            if previous == action_columns:
                continue
            for button in buttons:
                layout.removeWidget(button)
                button.setMinimumWidth(0)
                button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            for position, button in enumerate(buttons):
                row, column = divmod(position, action_columns)
                layout.addWidget(button, row, column)
            for column in range(len(buttons)):
                layout.setColumnStretch(column, 1 if column < action_columns else 0)
            if index < len(self._responsive_action_columns):
                self._responsive_action_columns[index] = action_columns
            else:
                self._responsive_action_columns.append(action_columns)


    def _populate_asr_models(self, engine_id: str, selected_model: str = "") -> None:
        """Populate choices from the selected adapter and retain unknown saved model IDs."""
        entry = self._asr_catalog.get(str(engine_id or "").strip().lower(), {})
        self.asr_model.blockSignals(True)
        try:
            self.asr_model.clear()
            for item in entry.get("models") or []:
                if not isinstance(item, dict):
                    continue
                model_id = str(item.get("id") or "").strip()
                if model_id:
                    self.asr_model.addItem(str(item.get("label") or model_id), model_id)
            if selected_model and self.asr_model.findData(selected_model) < 0:
                self.asr_model.addItem(f"مدل ذخیره‌شده در فهرست موتور نیست: {selected_model}", selected_model)
            if not self.asr_model.count() and selected_model:
                self.asr_model.addItem(f"مدل انتخاب‌شده: {selected_model}", selected_model)
            target = selected_model or str(entry.get("default_model") or "")
            index = self.asr_model.findData(target)
            if index < 0 and self.asr_model.count():
                index = 0
            self.asr_model.setCurrentIndex(index)
        finally:
            self.asr_model.blockSignals(False)

    def _on_asr_engine_changed(self, index: int) -> None:
        if index < 0:
            return
        engine_id = str(self.asr_backend.currentData() or "")
        entry = self._asr_catalog.get(engine_id, {})
        self._populate_asr_models(engine_id, str(entry.get("default_model") or ""))
        self._update_shenava_download_label()
        self._update_asr_engine_label()

    def _update_asr_engine_label(self) -> None:
        """Reflect the exact selected adapter; unsupported saved IDs stay visibly unsupported."""
        engine_id = str(self.asr_backend.currentData() or "").strip().lower()
        if engine_id not in self._asr_catalog:
            self.asr_engine_label.setText(f"ASR نامعتبر · {engine_id or 'unknown'}")
            return
        self.asr_engine_label.setText(f"{self.asr_backend.currentText()} · آفلاین")

    def _update_shenava_download_label(self) -> None:
        """Show model-specific download details provided by the adapter catalogue."""
        engine_id = str(self.asr_backend.currentData() or "")
        model_id = str(self.asr_model.currentData() or "")
        entry = self._asr_catalog.get(engine_id, {})
        metadata = next(
            (item for item in (entry.get("models") or []) if str(item.get("id") or "") == model_id),
            {},
        )
        label = str(metadata.get("label") or model_id or "مدل انتخاب نشده")
        size = metadata.get("size_mb")
        suffix = f" · حدود {size} مگابایت" if size else ""
        self.shenava_download_btn.setText(f"دانلود {label}{suffix}")

    def _update_live_toggle_text(self, enabled: bool | None = None) -> None:
        active = self.live_toggle.isChecked() if enabled is None else bool(enabled)
        if active:
            label = "توقف مکالمه صوتی"
        elif self.voice_engine.currentData() == "local":
            label = "شروع مکالمه محلی"
        else:
            label = "شروع مکالمه صوتی Gemini"
        self.live_toggle.setText(label)

    def refresh_gemini_providers(self, settings: dict) -> None:
        """Refresh Google connections without replacing a saved (possibly stale) selection."""
        combo = self.gemini_provider
        settings = {**SETTINGS_DEFAULTS, **(settings or {})}
        providers = []
        for provider_id, provider_cfg in (settings.get("providers") or {}).items():
            if not isinstance(provider_cfg, dict):
                continue
            pid = str(provider_id or "").strip().lower()
            is_google = (
                pid == "google"
                or pid.startswith("google_")
                or str(provider_cfg.get("service") or "").strip().lower() == "google"
                or "generativelanguage.googleapis.com" in str(provider_cfg.get("base_url") or "").lower()
            )
            if is_google:
                label = str(provider_cfg.get("label") or provider_id)
                if not str(provider_cfg.get("api_key") or "").strip():
                    label += " (کلید API خالی است)"
                providers.append((label, provider_id))

        selected = str(combo.currentData() or settings.get("gemini_live_provider") or "").strip()
        combo.blockSignals(True)
        try:
            combo.clear()
            provider_ids = {provider_id for _label, provider_id in providers}
            if selected and selected not in provider_ids:
                combo.addItem("اتصال Google ذخیره‌شده پیدا نشد؛ حساب دیگری جایگزین نشد", selected)
            for label, provider_id in providers:
                combo.addItem(label, provider_id)
            if not providers and not selected:
                combo.addItem("ابتدا Google AI Studio را در بخش اتصالات ثبت کن", "")
            index = combo.findData(selected)
            if index < 0 and not selected and combo.count():
                index = 0
            if index >= 0:
                combo.setCurrentIndex(index)
        finally:
            combo.blockSignals(False)
        combo.setEnabled(bool(providers) or bool(selected))
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
