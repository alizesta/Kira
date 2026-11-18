"""Static dependency-direction checks for Core and Application packages."""
from __future__ import annotations

import ast
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = ROOT / "kira" / "core"
APPLICATION_ROOT = ROOT / "kira" / "app"
CORE_FORBIDDEN_IMPORT_ROOTS = (
    "kira.app",
    "kira.ui",
    "PySide6",
    "PyQt5",
    "PyQt6",
)
APPLICATION_FORBIDDEN_IMPORT_ROOTS = (
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


def _dependency_violations(
    package_root: Path, forbidden_roots: tuple[str, ...], *, excluded: tuple[str, ...] = ()
) -> list[str]:
    violations: list[str] = []
    for source_path in sorted(package_root.rglob("*.py")):
        if source_path.name in excluded:
            continue
        relative = source_path.relative_to(ROOT)
        package = ".".join(relative.parent.parts)
        try:
            tree = ast.parse(source_path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            violations.append(
                f"{relative}:{exc.lineno}: syntax error: {exc.msg}"
            )
            continue

        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            for target in _import_targets(node, package):
                if any(
                    target == forbidden or target.startswith(forbidden + ".")
                    for forbidden in forbidden_roots
                ):
                    violations.append(f"{relative}:{node.lineno}: imports {target}")
    return violations


class ArchitectureDependencyBoundaryTests(unittest.TestCase):
    def test_core_does_not_depend_on_application_ui_or_qt(self):
        self.assertEqual(
            _dependency_violations(CORE_ROOT, CORE_FORBIDDEN_IMPORT_ROOTS),
            [],
            "Core must depend on contracts and standard-library abstractions, "
            "never on Application, Presentation, or Qt implementations.",
        )

    def test_application_services_do_not_depend_on_presentation_or_qt(self):
        # bootstrap.py is the outer Composition Root and is the sole allowed
        # place to construct QApplication and connect the UI shell.
        self.assertEqual(
            _dependency_violations(
                APPLICATION_ROOT,
                APPLICATION_FORBIDDEN_IMPORT_ROOTS,
                excluded=("bootstrap.py",),
            ),
            [],
            "Application services must remain independent of Presentation and Qt; "
            "only bootstrap may wire the UI shell.",
        )


if __name__ == "__main__":
    unittest.main()
