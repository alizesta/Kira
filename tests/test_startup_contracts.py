from __future__ import annotations

import ast
from pathlib import Path
import unittest

from kira.ui.window_presentation_context import ADAPTER_FIELDS


ROOT = Path(__file__).resolve().parents[1]


class StartupContractTests(unittest.TestCase):
    def test_music_watcher_is_a_declared_adapter(self):
        self.assertIn("music_watcher", ADAPTER_FIELDS)

    def test_chat_header_uses_the_project_qt_binding(self):
        source_path = ROOT / "kira" / "ui" / "components" / "chat_header.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported_modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }

        self.assertIn("PySide6.QtCore", imported_modules)
        self.assertIn("PySide6.QtWidgets", imported_modules)
        self.assertFalse(any(module.startswith("PyQt6") for module in imported_modules))


if __name__ == "__main__":
    unittest.main()
