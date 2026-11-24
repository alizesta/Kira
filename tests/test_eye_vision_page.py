"""Eye Vision settings tab: widget behaviour (offscreen Qt) and wiring/translation completeness."""
import os
import re
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from kira.strings import STR  # noqa: E402
from kira.ui.pages.eye_vision_page import EyeVisionPage  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
APP = QApplication.instance() or QApplication([])


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def make_page(lang="fa"):
    return EyeVisionPage(lambda key, **kw: STR[lang][key])


def test_every_label_key_exists_in_both_languages():
    keys = set(re.findall(r'"(eye_[a-z_]+)"', read("kira/ui/pages/eye_vision_page.py")))
    assert keys, "page must use translated labels"
    for lang in ("fa", "en"):
        assert sorted(key for key in keys | {"tab_eye"} if key not in STR[lang]) == []


def test_tab_is_registered_lazily_and_after_existing_tabs():
    source = read("kira/ui/main_window_composition.py")
    assert '"tab_general", "tab_ai", "tab_eye"]' in source
    assert '6: ("tab_eye", _build_eye_tab)' in source
    assert 'build_eye_vision_page()' in source


def test_profile_is_loaded_from_settings_with_competitive_safe_default():
    source = read("kira/ui/main_window_composition.py")
    assert 'normalize_profile(' in source and 'settings.get("eye_mode_profile")' in source
    from kira.config import DEFAULTS
    assert DEFAULTS["eye_mode_profile"] == "competitive_safe"
    assert DEFAULTS["eye_live_max_frames_per_minute"] <= 12
    assert DEFAULTS["eye_live_min_interval_seconds"] >= 5


def test_switching_profile_in_the_page_emits_once_and_set_profile_is_silent():
    page = make_page()
    seen = []
    page.profile_selected.connect(seen.append)
    page.set_profile("story")  # programmatic state must not look like a user change
    assert seen == [] and page.profile_story.isChecked() and not page.profile_safe.isChecked()
    page.profile_safe.setChecked(True)
    assert seen == ["competitive_safe"]


def test_set_profile_defaults_to_safe_for_unknown_values():
    page = make_page()
    page.set_profile("anything")
    assert page.profile_safe.isChecked()


def test_eye_switch_emits_for_user_but_not_for_programmatic_sync():
    page = make_page()
    seen = []
    page.eye_mode_toggled.connect(seen.append)
    page.set_eye_enabled(True)
    assert seen == [] and page.eye_switch.isChecked()
    page.eye_switch.setChecked(False)
    assert seen == [False]


def test_monitor_combo_lists_auto_first_and_reports_the_choice():
    page = make_page()
    page.set_monitors([("m1", "Monitor 1 · اصلی"), ("m2", "Monitor 2")], "m2")
    assert page.monitor_combo.count() == 3
    assert page.monitor_combo.itemData(0) == ""
    assert page.monitor_combo.currentData() == "m2"
    seen = []
    page.monitor_selected.connect(seen.append)
    page.monitor_combo.activated.emit(0)
    assert seen == [""]
    page.select_monitor("missing")  # a monitor that vanished falls back to automatic
    assert page.monitor_combo.currentData() == ""


def test_budget_estimate_follows_the_stricter_limit_and_changes_emit_once_each():
    page = make_page("en")
    page.set_budget(5, 10)
    assert page.max_frames_per_hour() == 600
    assert "600" in page.budget_estimate.text()
    seen = []
    page.frame_budget_changed.connect(lambda interval, per_minute: seen.append((interval, per_minute)))
    page.fpm_spin.setValue(4)
    assert seen == [(5.0, 4)] and page.max_frames_per_hour() == 240
    page.interval_spin.setValue(30)  # 120/hour by interval is now stricter than 240/hour by count
    assert seen[-1] == (30.0, 4) and page.max_frames_per_hour() == 120


def test_translations_can_be_registered_and_rebound():
    page = make_page("fa")
    registered = []
    page.bind_translations(lambda setter, key: registered.append((setter, key)))
    assert len(registered) >= 14
    for setter, key in registered:
        setter(STR["en"][key])
    assert page.eye_switch.text() == STR["en"]["eye_toggle"]
    assert page.profile_box.title() == STR["en"]["eye_sec_profile"]
    assert "{n}" not in page.budget_estimate.text()


def test_controller_builds_the_page_and_never_enables_eye_mode_from_the_profile_setter():
    source = read("kira/ui/main_window_attachments_vision.py")
    body = source.split("    def set_eye_mode_profile", 1)[1].split("    def _eye_monitor_choices", 1)[0]
    assert 'settings["eye_mode_profile"] = normalized' in body
    assert "if self.context.state._game_mode_enabled:" in body
    assert "self.set_game_mode(True)" not in body
    assert "page.eye_mode_toggled.connect" in source
    assert "game_mode_btn.toggled.connect(page.set_eye_enabled)" in source
    assert "self._live_selector().policy = self._live_policy()" in source
