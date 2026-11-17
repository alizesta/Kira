"""Regression test: the legacy application entry module must remain valid Python."""
import ast
from pathlib import Path
import unittest


class OldMainSyntaxTests(unittest.TestCase):
    def test_oldmain_parses_as_valid_python(self):
        source = Path(__file__).resolve().parents[1] / "kira" / "oldmain.py"
        ast.parse(source.read_text(encoding="utf-8"), filename=str(source))


if __name__ == "__main__":
    unittest.main()
