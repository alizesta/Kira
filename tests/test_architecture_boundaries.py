"""Static dependency-direction checks for the Core package."""
from __future__ import annotations

import ast
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = ROOT / "kira" / "core"
FORBIDDEN_IMPORT_ROOTS = (
    "kira.app",
    "kira.ui",
    "PySide6",
    "PyQt5",
    "PyQt6",
)


def _import_targets(node: ast.AST, package: str) -> set[str]:
    """Resolve absolute and relative imports, including from-dot imports."""
    targets: set[str] = set()
    if isinstance(node, ast.Import):
        targets.update(alias.name for alias in node.names)
    elif isinstance(node, ast.ImportFrom):
        if node.level:
            base = importlib.util.resolve_name(
                "." * node.level + (node.module or ""), package
            )
        else:
            base = node.module or ""
        if base:
            targets.add(base)
        for alias in node.names:
            if alias.name != "*":
                targets.add(f"{base}.{alias.name}" if base else alias.name)
    return targets


class CoreDependencyBoundaryTests(unittest.TestCase):
    def test_core_does_not_depend_on_application_ui_or_qt(self):
        violations: list[str] = []
        for source_path in sorted(CORE_ROOT.rglob("*.py")):
            relative = source_path.relative_to(ROOT)
            package = ".".join(relative.parent.parts)
            try:
                tree = ast.parse(source_path.read_text(encoding="utf-8"))
            except SyntaxError as exc:
                self.fail(f"Core source does not parse: {relative}:{exc.lineno}: {exc.msg}")

            for node in ast.walk(tree):
                if not isinstance(node, (ast.Import, ast.ImportFrom)):
                    continue
                for target in _import_targets(node, package):
                    if any(
                        target == forbidden or target.startswith(forbidden + ".")
                        for forbidden in FORBIDDEN_IMPORT_ROOTS
                    ):
                        violations.append(
                            f"{relative}:{node.lineno}: imports {target}"
                        )

        self.assertEqual(
            violations,
            [],
            "Core must depend on contracts and standard-library abstractions, "
            "never on Application, Presentation, or Qt implementations.",
        )


if __name__ == "__main__":
    unittest.main()
