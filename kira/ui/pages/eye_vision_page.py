"""Eye Vision settings page: Eye Mode switch, monitor, game profile and Gemini Live frame budget.

The page owns only widgets and signals. It never touches settings, capture or Live state; the
attachments/vision controller connects the signals to the real services.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from kira.ui.components.switch_checkbox import SwitchCheckBox

COMPETITIVE_SAFE = "competitive_safe"
STORY = "story"
AUTO_MONITOR = ""


class EyeVisionPage(QWidget):
    eye_mode_toggled = Signal(bool)
    monitor_selected = Signal(str)
    profile_selected = Signal(str)
    frame_budget_changed = Signal(float, int)
    refresh_requested = Signal()

    def __init__(self, translate: Callable[..., str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("eyeVisionPage")
        self._t = translate
        self._texts: list[tuple[Callable[[str], None], str]] = []
        self._estimate_template = "{n}"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        # -- Eye Mode on/off
        self.mode_box = QGroupBox()
        mode_layout = QVBoxLayout(self.mode_box)
        self.eye_switch = SwitchCheckBox()
        self.mode_hint = self._hint_label()
        mode_layout.addWidget(self.eye_switch)
        mode_layout.addWidget(self.mode_hint)
        self.eye_switch.toggled.connect(self.eye_mode_toggled)
        root.addWidget(self.mode_box)

        # -- monitor
        self.monitor_box = QGroupBox()
        monitor_layout = QVBoxLayout(self.monitor_box)
        self.monitor_combo = QComboBox()
        monitor_layout.addWidget(self.monitor_combo)
        self.monitor_combo.activated.connect(self._on_monitor_activated)
        root.addWidget(self.monitor_box)

        # -- game profile
        self.profile_box = QGroupBox()
        profile_layout = QVBoxLayout(self.profile_box)
        self.profile_safe = QRadioButton()
        self.profile_story = QRadioButton()
        self.profile_hint = self._hint_label()
        for button in (self.profile_safe, self.profile_story):
            profile_layout.addWidget(button)
        profile_layout.addWidget(self.profile_hint)
        self.profile_safe.toggled.connect(lambda on: on and self.profile_selected.emit(COMPETITIVE_SAFE))
        self.profile_story.toggled.connect(lambda on: on and self.profile_selected.emit(STORY))
        root.addWidget(self.profile_box)

        # -- Gemini Live frame budget
        self.budget_box = QGroupBox()
        budget_layout = QVBoxLayout(self.budget_box)
        form = QFormLayout()
        self.interval_label = QLabel()
        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setRange(1.0, 60.0)
        self.interval_spin.setSingleStep(1.0)
        self.interval_spin.setDecimals(0)
        self.fpm_label = QLabel()
        self.fpm_spin = QSpinBox()
        self.fpm_spin.setRange(1, 60)
        form.addRow(self.interval_label, self.interval_spin)
        form.addRow(self.fpm_label, self.fpm_spin)
        self.budget_estimate = self._hint_label()
        self.budget_hint = self._hint_label()
        budget_layout.addLayout(form)
        budget_layout.addWidget(self.budget_estimate)
        budget_layout.addWidget(self.budget_hint)
        self.interval_spin.valueChanged.connect(self._on_budget_changed)
        self.fpm_spin.valueChanged.connect(self._on_budget_changed)
        root.addWidget(self.budget_box)
        root.addStretch()

        self._bind(self.mode_box.setTitle, "eye_sec_mode")
        self._bind(self.eye_switch.setText, "eye_toggle")
        self._bind(self.mode_hint.setText, "eye_toggle_hint")
        self._bind(self.monitor_box.setTitle, "eye_sec_monitor")
        self._bind(self._set_auto_monitor_text, "eye_monitor_auto")
        self._bind(self.profile_box.setTitle, "eye_sec_profile")
        self._bind(self.profile_safe.setText, "eye_profile_safe")
        self._bind(self.profile_story.setText, "eye_profile_story")
        self._bind(self.profile_hint.setText, "eye_profile_hint")
        self._bind(self.budget_box.setTitle, "eye_sec_budget")
        self._bind(self.interval_label.setText, "eye_budget_interval")
        self._bind(self.fpm_label.setText, "eye_budget_fpm")
        self._bind(self._set_estimate_template, "eye_budget_estimate")
        self._bind(self.budget_hint.setText, "eye_budget_hint")
        self.profile_safe.setChecked(True)
        self._refresh_estimate()

    # ------------------------------------------------------------------ translation
    @staticmethod
    def _hint_label() -> QLabel:
        label = QLabel()
        label.setWordWrap(True)
        label.setEnabled(False)
        return label

    def _bind(self, setter: Callable[[str], None], key: str) -> None:
        self._texts.append((setter, key))
        setter(self._t(key))

    def bind_translations(self, register: Callable[[Callable[[str], None], str], None]) -> None:
        """Register every label with the window's language switch (same hook as other pages)."""
        for setter, key in self._texts:
            register(setter, key)

    def _set_auto_monitor_text(self, text: str) -> None:
        if self.monitor_combo.count() and self.monitor_combo.itemData(0) == AUTO_MONITOR:
            self.monitor_combo.setItemText(0, text)

    def _set_estimate_template(self, text: str) -> None:
        self._estimate_template = text
        self._refresh_estimate()

    # ------------------------------------------------------------------ state in
    def set_eye_enabled(self, enabled: bool) -> None:
        self.eye_switch.blockSignals(True)
        self.eye_switch.setChecked(bool(enabled))
        self.eye_switch.blockSignals(False)
        self.eye_switch.update()

    def set_monitors(self, monitors: list[tuple[str, str]], selected_id: str = AUTO_MONITOR) -> None:
        self.monitor_combo.blockSignals(True)
        self.monitor_combo.clear()
        self.monitor_combo.addItem(self._t("eye_monitor_auto"), AUTO_MONITOR)
        for monitor_id, label in monitors:
            self.monitor_combo.addItem(label, str(monitor_id))
        self.select_monitor(selected_id)
        self.monitor_combo.blockSignals(False)

    def select_monitor(self, monitor_id: str) -> None:
        index = self.monitor_combo.findData(str(monitor_id or AUTO_MONITOR))
        self.monitor_combo.blockSignals(True)
        self.monitor_combo.setCurrentIndex(index if index >= 0 else 0)
        self.monitor_combo.blockSignals(False)

    def set_profile(self, profile: str) -> None:
        story = str(profile) == STORY
        for button, checked in ((self.profile_safe, not story), (self.profile_story, story)):
            button.blockSignals(True)
            button.setChecked(checked)
            button.blockSignals(False)

    def set_budget(self, interval_seconds: float, frames_per_minute: int) -> None:
        for spin, value in ((self.interval_spin, float(interval_seconds)), (self.fpm_spin, int(frames_per_minute))):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        self._refresh_estimate()

    # ------------------------------------------------------------------ state out / events
    def max_frames_per_hour(self) -> int:
        interval = max(1.0, float(self.interval_spin.value()))
        return int(min(3600.0 / interval, self.fpm_spin.value() * 60))

    def _refresh_estimate(self) -> None:
        self.budget_estimate.setText(self._estimate_template.replace("{n}", str(self.max_frames_per_hour())))

    def _on_monitor_activated(self, index: int) -> None:
        self.monitor_selected.emit(str(self.monitor_combo.itemData(index) or AUTO_MONITOR))

    def _on_budget_changed(self, _value=None) -> None:
        self._refresh_estimate()
        self.frame_budget_changed.emit(float(self.interval_spin.value()), int(self.fpm_spin.value()))

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        self.refresh_requested.emit()
