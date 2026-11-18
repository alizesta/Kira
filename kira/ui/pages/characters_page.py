"""Independent profile and personality controls for Kira, Ren and Mika."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class CharactersPage(QScrollArea):
    """Own character-management widgets and emit intent to the app controller.

    The page knows neither the character storage package nor chat sessions,
    avatars, speaker engines or persistence. The host connects its signals to
    application-level actions and supplies profile data through the widgets.
    """

    character_selected = Signal(int)
    add_character_requested = Signal()
    edit_character_requested = Signal()
    delete_character_requested = Signal()
    choose_theme_color_requested = Signal()
    reset_theme_color_requested = Signal()
    preview_requested = Signal(object)
    open_sounds_requested = Signal()
    save_requested = Signal()
    save_personality_requested = Signal()

    def __init__(
        self,
        settings: dict,
        translate: Callable[[str], str],
        *,
        base_traits: dict[str, float],
        moods: list[str] | tuple[str, ...],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._translate = translate
        self._translations: list[tuple[Callable[[str], None], str]] = []
        settings = settings or {}
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        subtabs = QTabWidget()
        self.character_subtabs = subtabs

        box, form = self._group("g_char")
        self.character_combo = QComboBox()
        self.character_portrait = QLabel()
        self.character_portrait.setObjectName("characterPortrait")
        self.character_portrait.setFixedSize(144, 180)
        self.character_portrait.setScaledContents(True)
        self.character_description = QLabel()
        self.character_description.setWordWrap(True)
        profile_row = QHBoxLayout()
        profile_row.addWidget(self.character_portrait)
        profile_info = QVBoxLayout()
        profile_info.addWidget(QLabel("شخصیت فعال"))
        profile_info.addWidget(self.character_combo)
        profile_info.addWidget(self.character_description)

        manager_row = QHBoxLayout()
        self.character_add_btn = QPushButton("＋")
        self.character_add_btn.setFixedWidth(38)
        self.character_add_btn.setToolTip("ساخت شخصیت جدید")
        self.character_edit_btn = QPushButton("ویرایش")
        self.character_delete_btn = QPushButton("حذف")
        self.character_add_btn.clicked.connect(lambda checked=False: self.add_character_requested.emit())
        self.character_edit_btn.clicked.connect(lambda checked=False: self.edit_character_requested.emit())
        self.character_delete_btn.clicked.connect(lambda checked=False: self.delete_character_requested.emit())
        manager_row.addWidget(self.character_add_btn)
        manager_row.addWidget(self.character_edit_btn)
        manager_row.addWidget(self.character_delete_btn)
        profile_info.addLayout(manager_row)

        theme_row = QHBoxLayout()
        self.character_theme_color_btn = QPushButton("انتخاب رنگ تم")
        self.character_theme_color_btn.clicked.connect(lambda checked=False: self.choose_theme_color_requested.emit())
        self.character_theme_color_preview = QLabel("#9C7BFF")
        self.character_theme_color_preview.setMinimumWidth(82)
        self.character_theme_color_preview.setAlignment(Qt.AlignCenter)
        theme_row.addWidget(self.character_theme_color_btn)
        theme_row.addWidget(self.character_theme_color_preview)
        self.character_theme_reset_btn = QPushButton("بازنشانی رنگ")
        self.character_theme_reset_btn.clicked.connect(lambda checked=False: self.reset_theme_color_requested.emit())
        theme_row.addWidget(self.character_theme_reset_btn)
        profile_info.addLayout(theme_row)
        profile_row.addLayout(profile_info, 1)
        form.addRow(profile_row)

        voice_box, voice_form = self._group("تن صدا و سرعت شخصیت")
        self.char_voice_rate = QSpinBox()
        self.char_voice_rate.setRange(-30, 30)
        self.char_voice_rate.setSuffix(" %")
        voice_form.addRow("سرعت گفتار محلی", self.char_voice_rate)
        self.char_voice_volume = QSlider(Qt.Horizontal)
        self.char_voice_volume.setRange(0, 100)
        voice_form.addRow("بلندی صدا", self.char_voice_volume)
        voice_note = QLabel(
            "همه‌ی شخصیت‌ها از موتور Piper محلی استفاده می‌کنند؛ فقط سرعت و بلندی صدای هر شخصیت جداست."
        )
        voice_note.setObjectName("hint")
        voice_note.setWordWrap(True)
        voice_form.addRow(voice_note)
        form.addRow(voice_box)

        resource_box, resource_form = self._group("منابع اختصاصی شخصیت")
        self.char_skills_edit = QLineEdit()
        self.char_skills_edit.setPlaceholderText("نام Skillها، با کاما جدا کن")
        resource_form.addRow("Skills", self.char_skills_edit)
        self.char_mcp_edit = QLineEdit()
        self.char_mcp_edit.setPlaceholderText("نام MCPها یا سرورها")
        resource_form.addRow("MCP", self.char_mcp_edit)
        self.char_connectors_edit = QLineEdit()
        self.char_connectors_edit.setPlaceholderText("نام Connectorها")
        resource_form.addRow("Connectors", self.char_connectors_edit)
        form.addRow(resource_box)

        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(550)
        self.save_timer.timeout.connect(self.save_requested.emit)
        self.char_voice_rate.valueChanged.connect(lambda *_: self.save_timer.start())
        self.char_voice_volume.valueChanged.connect(lambda *_: self.save_timer.start())
        for widget in (self.char_skills_edit, self.char_mcp_edit, self.char_connectors_edit):
            widget.textChanged.connect(lambda *_: self.save_timer.start())

        self.size_sl = self._row(form, "char_size", QSlider(Qt.Horizontal))
        self.size_sl.setRange(300, 1000)
        self.size_sl.setValue(int(settings["companion_height"]))
        self.follow_sl = self._row(form, "follow", QSlider(Qt.Horizontal))
        self.follow_sl.setRange(0, 150)
        self.follow_sl.setValue(int(float(settings["follow_strength"]) * 100))
        self.motion_sl = self._row(form, "motion", QSlider(Qt.Horizontal))
        self.motion_sl.setRange(0, 200)
        self.motion_sl.setValue(int(float(settings["motion_strength"]) * 100))

        self.react_chk = QCheckBox()
        self.react_chk.setChecked(bool(settings["click_reactions"]))
        self._register(self.react_chk.setText, "reactions")
        self.top_chk = QCheckBox()
        self.top_chk.setChecked(bool(settings["always_on_top"]))
        self._register(self.top_chk.setText, "on_top")
        self.idle_chk = QCheckBox()
        self.idle_chk.setChecked(bool(settings.get("idle_talk", True)))
        self._register(self.idle_chk.setText, "idle_talk")
        form.addRow(self.react_chk)
        form.addRow(self.idle_chk)
        form.addRow(self.top_chk)

        self.tray_min_chk = QCheckBox("با دکمه‌ی Minimize به System Tray برود")
        self.tray_min_chk.setChecked(bool(settings.get("minimize_to_tray", True)))
        self.tray_close_chk = QCheckBox("با دکمه‌ی بستن (X) به System Tray برود و بسته نشود")
        self.tray_close_chk.setChecked(bool(settings.get("close_to_tray", False)))
        form.addRow(self.tray_min_chk)
        form.addRow(self.tray_close_chk)

        self.mood_combo = QComboBox()
        for mood in moods:
            self.mood_combo.addItem(str(mood), mood)
        preview = QPushButton()
        self._register(preview.setText, "preview")
        preview.clicked.connect(lambda: self.preview_requested.emit(self.mood_combo.currentData()))
        mood_row = QHBoxLayout()
        mood_row.addWidget(self.mood_combo, 1)
        mood_row.addWidget(preview)
        mood_label = QLabel()
        self._register(mood_label.setText, "mood_preview")
        form.addRow(mood_label, mood_row)

        sounds = QPushButton()
        self._register(sounds.setText, "open_sounds")
        sounds.clicked.connect(lambda checked=False: self.open_sounds_requested.emit())
        form.addRow(sounds)
        note = QLabel()
        note.setObjectName("hint")
        note.setWordWrap(True)
        self._register(note.setText, "char_note")
        form.addRow(note)

        personality_box, personality_form = self._group("g_personality_traits")
        labels = {
            "playfulness": "trait_playfulness",
            "warmth": "trait_warmth",
            "curiosity": "trait_curiosity",
            "confidence": "trait_confidence",
            "assertiveness": "trait_assertiveness",
            "teasing": "trait_teasing",
            "empathy": "trait_empathy",
            "independence": "trait_independence",
            "patience": "trait_patience",
            "carefulness": "trait_carefulness",
        }
        self.personality_sliders: dict[str, QSlider] = {}
        self.character_notes_edit = QTextEdit()
        self.character_notes_edit.setMaximumHeight(96)
        self.character_notes_edit.setPlaceholderText(
            "لحن، رفتار، علاقه‌ها و مرزهای شخصیت را اینجا بنویس…"
        )
        self.character_notes_edit.textChanged.connect(lambda: self.save_timer.start())
        personality_form.addRow("پرسونالیتی و یادداشت‌های شخصیت", self.character_notes_edit)
        for key, translation_key in labels.items():
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(int(round(float(base_traits.get(key, 0.5)) * 100)))
            self._row(personality_form, translation_key, slider)
            self.personality_sliders[key] = slider
        personality_hint = QLabel()
        personality_hint.setObjectName("hint")
        personality_hint.setWordWrap(True)
        self._register(personality_hint.setText, "personality_hint")
        personality_form.addRow(personality_hint)
        save_traits = QPushButton()
        self._register(save_traits.setText, "character_save_traits")
        save_traits.clicked.connect(lambda checked=False: self.save_personality_requested.emit())
        personality_form.addRow(save_traits)

        subtabs.addTab(self._page(box), "")
        subtabs.addTab(self._page(personality_box), "")
        self._register(lambda value: subtabs.setTabText(0, value), "tab_characters")
        self._register(lambda value: subtabs.setTabText(1, value), "tab_personality")
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        layout.addWidget(subtabs)
        self.setWidget(host)

        self.character_combo.currentIndexChanged.connect(lambda index: self.character_selected.emit(index))
        self.retranslate()

    def _register(self, setter: Callable[[str], None], key: str) -> None:
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

    @staticmethod
    def _page(*widgets: QWidget) -> QScrollArea:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        for widget in widgets:
            layout.addWidget(widget)
        layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(host)
        return scroll

    def retranslate(self) -> None:
        for setter, key in self._translations:
            setter(self._translate(key))
