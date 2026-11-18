"""Regression test: all extracted desktop-window modules must remain valid Python."""
import ast
from pathlib import Path
import unittest


class MainWindowSyntaxTests(unittest.TestCase):
    def test_all_window_modules_parse_as_valid_python(self):
        root = Path(__file__).resolve().parents[1] / "kira" / "ui"
        sources = [root / "main_window.py", root / "main_window_support.py", root / "window_feature_controller.py"]
        sources.extend(sorted(root.glob("main_window_*.py")))
        for source in set(sources):
            ast.parse(source.read_text(encoding="utf-8"), filename=str(source))


if __name__ == "__main__":
    unittest.main()
