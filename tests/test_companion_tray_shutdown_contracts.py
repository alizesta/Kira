"""Regression guards for companion bubble and tray shutdown contracts.

These checks intentionally use only the Python standard library, so the safety
contracts remain testable on hosts that do not have the Qt runtime installed.
"""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

from kira.ui.companion_session import session_marker


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _method(relative_path: str, method_name: str) -> ast.FunctionDef:
    tree = ast.parse(_source(relative_path), filename=relative_path)
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.Module)):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == method_name:
                    return child
    raise AssertionError(f"{method_name} not found in {relative_path}")


def _call_names(node: ast.AST) -> set[str]:
    return {
        child.func.attr
        for child in ast.walk(node)
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
    }


class CompanionSessionMarkerTests(unittest.TestCase):
    def test_prefers_native_session_id(self):
        class Session:
            session_id = "session-42"
            cid = "ren"
            conversation_id = "conversation-9"

        self.assertEqual(session_marker(Session()), "session-42")

    def test_legacy_session_uses_character_and_conversation_ids(self):
        class LegacySession:
            cid = "mika"
            conversation_id = "conversation-legacy"

        self.assertEqual(
            session_marker(LegacySession()),
            ("mika", "conversation-legacy"),
        )


class CompanionTrayShutdownContractTests(unittest.TestCase):
    def test_tray_is_only_hidden_after_the_close_protocol_accepts(self):
        lifecycle_quit = _method("kira/ui/main_window_lifecycle.py", "quit_app")
        self.assertNotIn("hide", _call_names(lifecycle_quit))
        self.assertNotIn("setQuitOnLastWindowClosed", _call_names(lifecycle_quit))

        close_event = _method("kira/ui/main_window_runtime.py", "closeEvent")
        close_source = ast.get_source_segment(
            _source("kira/ui/main_window_runtime.py"), close_event
        )
        self.assertNotIn("views.tray.hide", close_source)
        self.assertIn(
            "event.accept()\n        QTimer.singleShot(0, self._exit_application)",
            close_source,
        )

        exit_application = _method("kira/ui/main_window_runtime.py", "_exit_application")
        exit_calls = _call_names(exit_application)
        self.assertIn("hide", exit_calls)
        self.assertIn("setQuitOnLastWindowClosed", exit_calls)
        self.assertIn("quit", exit_calls)

    def test_escape_closes_the_composer_and_returns_to_preview(self):
        source = _source("kira/companion.py")
        self.assertIn(
            "self._escape_shortcut.activated.connect(self.close_composer)",
            source,
        )
        self.assertIn(
            "self._escape_shortcut.setContext(Qt.WidgetWithChildrenShortcut)",
            source,
        )
        close_composer = _method("kira/companion.py", "close_composer")
        calls = _call_names(close_composer)
        self.assertIn("show_preview", calls)
        self.assertIn("hide", calls)

    def test_preview_remains_latest_only_and_expires_after_ten_seconds(self):
        source = _source("kira/companion.py")
        self.assertIn("self._preview_timer.start(10000)", source)
        self.assertIn("visible_items = self.items[-1:]", source)

    def test_bubble_closes_only_after_shutdown_is_accepted(self):
        close_event = _method("kira/ui/main_window_runtime.py", "closeEvent")
        self.assertNotIn("bubble.close", ast.get_source_segment(
            _source("kira/ui/main_window_runtime.py"), close_event
        ))
        exit_application = _method("kira/ui/main_window_runtime.py", "_exit_application")
        self.assertIn("close", _call_names(exit_application))
        self.assertIn('getattr(self.context.adapters, "bubble", None)', ast.get_source_segment(
            _source("kira/ui/main_window_runtime.py"), exit_application
        ))

    def test_bubble_panel_is_more_transparent(self):
        source = _source("kira/companion.py")
        self.assertIn("background:rgba(24,26,40,88)", source)
        self.assertNotIn("background:rgba(24,26,40,150)", source)


if __name__ == "__main__":
    unittest.main()
