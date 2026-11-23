"""Regression tests for voice settings that are created lazily."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_VOICE_SOURCE = ROOT / "kira" / "ui" / "main_window_runtime_voice.py"


class _Label:
    def __init__(self):
        self.text = None

    def setText(self, value):
        self.text = value


class RuntimeVoiceEngineLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse(RUNTIME_VOICE_SOURCE.read_text(encoding="utf-8"))
        mixin = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "RuntimeVoiceMixin"
        )
        method = next(
            node for node in mixin.body
            if isinstance(node, ast.FunctionDef) and node.name == "update_engine_label"
        )
        isolated_module = ast.fix_missing_locations(
            ast.Module(body=[method], type_ignores=[])
        )
        namespace = {}
        exec(compile(isolated_module, str(RUNTIME_VOICE_SOURCE), "exec"), namespace)
        cls.update_engine_label = staticmethod(namespace["update_engine_label"])

    def _controller(self, mode="idle"):
        views = SimpleNamespace()
        context = SimpleNamespace(views=views, listener=None)
        return SimpleNamespace(context=context, _voice_mode=mode)

    def test_startup_retranslation_is_safe_before_voice_page_is_built(self):
        controller = self._controller()

        # This mirrors the strict views bucket: an absent, declared field raises
        # AttributeError instead of silently returning None.
        class StrictViews:
            def __getattr__(self, name):
                raise AttributeError(f"views.{name} has not been initialized")

        controller.context.views = StrictViews()
        self.update_engine_label(controller)

    def test_lazy_page_receives_engine_label_after_it_is_created(self):
        controller = self._controller()
        self.update_engine_label(controller)

        label = _Label()
        controller.context.views.voice_page = SimpleNamespace(engine_lbl=label)
        self.update_engine_label(controller)

        self.assertEqual(label.text, "—")

    def test_gemini_live_states_update_the_label(self):
        controller = self._controller("gemini_connecting")
        label = _Label()
        controller.context.views.voice_page = SimpleNamespace(engine_lbl=label)

        self.update_engine_label(controller)
        self.assertEqual(label.text, "Gemini Live · در حال اتصال")

        controller._voice_mode = "gemini_live"
        self.update_engine_label(controller)
        self.assertEqual(label.text, "Gemini Live · Cloud")



class _CheckableControl:
    def __init__(self, checked=False, blocked=False):
        self.checked = bool(checked)
        self.blocked = bool(blocked)
        self.block_calls = []
        self.checked_while_blocked = None
        self.tooltip = None
        self.icons = {"voiceOnIcon": "voice-on", "voiceOffIcon": "voice-off"}
        self.icon = None

    def blockSignals(self, block):
        previous = self.blocked
        self.blocked = bool(block)
        self.block_calls.append(bool(block))
        return previous

    def setChecked(self, value):
        self.checked = bool(value)
        self.checked_while_blocked = self.blocked

    def setToolTip(self, value):
        self.tooltip = value

    def property(self, name):
        return self.icons.get(name)

    def setIcon(self, icon):
        self.icon = icon


class RuntimeVoiceToggleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse(RUNTIME_VOICE_SOURCE.read_text(encoding="utf-8"))
        mixin = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "RuntimeVoiceMixin"
        )
        method = next(
            node for node in mixin.body
            if isinstance(node, ast.FunctionDef) and node.name == "set_voice_enabled"
        )
        cls.saved_settings = []

        def _save_settings(settings):
            cls.saved_settings.append(dict(settings))

        isolated_module = ast.fix_missing_locations(
            ast.Module(body=[method], type_ignores=[])
        )
        namespace = {"save_settings": _save_settings}
        exec(compile(isolated_module, str(RUNTIME_VOICE_SOURCE), "exec"), namespace)
        cls.set_voice_enabled = staticmethod(namespace["set_voice_enabled"])

    def setUp(self):
        self.saved_settings.clear()
        self.stop_calls = []

    def _controller(self, views, settings=None):
        context = SimpleNamespace(
            views=views,
            services=SimpleNamespace(settings=settings if settings is not None else {}),
        )
        return SimpleNamespace(
            context=context,
            safe_stop_speaker=lambda: self.stop_calls.append(True),
        )

    def test_toggle_is_safe_before_lazy_voice_page_exists(self):
        button = _CheckableControl(checked=False, blocked=False)

        class StrictViews:
            def __init__(self):
                self.voice_btn = button
                self.lookups = []

            def __getattr__(self, name):
                self.lookups.append(name)
                raise AttributeError(f"views.{name} has not been initialized")

        views = StrictViews()
        settings = {}
        controller = self._controller(views, settings)

        self.set_voice_enabled(controller, True)

        self.assertEqual(settings["speak_replies"], True)
        self.assertTrue(button.checked)
        self.assertTrue(button.checked_while_blocked)
        self.assertFalse(button.blocked)
        self.assertEqual(button.block_calls, [True, False])
        self.assertEqual(button.tooltip, "پاسخ صوتی روشن است؛ Kira با صدا پاسخ می‌دهد.")
        self.assertEqual(button.icon, "voice-on")
        self.assertEqual(views.lookups, ["voice_page"])
        self.assertEqual(self.saved_settings, [{"speak_replies": True}])
        self.assertEqual(self.stop_calls, [])

    def test_toggle_updates_both_controls_and_restores_prior_signal_states(self):
        button = _CheckableControl(checked=True, blocked=True)
        speak_checkbox = _CheckableControl(checked=True, blocked=False)
        views = SimpleNamespace(
            voice_btn=button,
            voice_page=SimpleNamespace(speak_chk=speak_checkbox),
        )
        settings = {}
        controller = self._controller(views, settings)

        self.set_voice_enabled(controller, False)

        self.assertFalse(button.checked)
        self.assertFalse(speak_checkbox.checked)
        self.assertTrue(button.checked_while_blocked)
        self.assertTrue(speak_checkbox.checked_while_blocked)
        self.assertTrue(button.blocked)       # preserve the pre-existing blocked state
        self.assertFalse(speak_checkbox.blocked)
        self.assertEqual(button.block_calls, [True, True])
        self.assertEqual(speak_checkbox.block_calls, [True, False])
        self.assertEqual(button.tooltip, "پاسخ صوتی خاموش است؛ Kira فقط متنی پاسخ می‌دهد.")
        self.assertEqual(button.icon, "voice-off")
        self.assertEqual(self.saved_settings, [{"speak_replies": False}])
        self.assertEqual(self.stop_calls, [True])

    def test_toggle_is_safe_when_page_exists_without_speak_checkbox(self):
        button = _CheckableControl()
        views = SimpleNamespace(voice_btn=button, voice_page=SimpleNamespace())
        controller = self._controller(views)

        self.set_voice_enabled(controller, True)

        self.assertTrue(button.checked)
        self.assertEqual(button.block_calls, [True, False])


if __name__ == "__main__":
    unittest.main()
