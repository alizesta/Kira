from __future__ import annotations

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class StartupContractTests(unittest.TestCase):
    def test_music_watcher_is_a_declared_adapter(self):
        source_path = ROOT / "kira" / "ui" / "window_presentation_context.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        declaration = next(
            node
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "ADAPTER_FIELDS" for target in node.targets)
        )
        fields = ast.literal_eval(declaration.value.args[0])
        self.assertIn("music_watcher", fields)

    def test_chat_components_use_the_project_qt_binding(self):
        for component in ("chat_header.py", "chat_composer.py"):
            with self.subTest(component=component):
                source_path = ROOT / "kira" / "ui" / "components" / component
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
