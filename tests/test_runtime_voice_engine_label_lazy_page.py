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


if __name__ == "__main__":
    unittest.main()
