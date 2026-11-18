"""Static, Qt-free checks for the package dependency direction."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QT_IMPORT_PREFIXES = ("PySide6", "PySide2", "PyQt5", "PyQt6")
CORE_ALLOWED_PACKAGE_PREFIXES = ("kira.core", "kira.domain")
APPLICATION_FORBIDDEN_PREFIXES = ("kira.ui", *QT_IMPORT_PREFIXES)


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imported_modules(path: Path) -> list[str]:
    """Return absolute import targets, resolving relative imports from the file."""
    module_name = _module_name(path)
    is_package = path.name == "__init__.py"
    package_parts = module_name.split(".") if is_package else module_name.split(".")[:-1]
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                keep = max(0, len(package_parts) - node.level + 1)
                target_parts = package_parts[:keep]
                if node.module:
                    target_parts.extend(node.module.split("."))
                target = ".".join(target_parts)
            else:
                target = node.module or ""
            if target:
                imported.append(target)
                imported.extend(
                    f"{target}.{alias.name}"
                    for alias in node.names
                    if alias.name != "*"
                )
    return imported


def _matches_prefix(module_name: str, prefixes: tuple[str, ...]) -> bool:
    return any(
        module_name == prefix or module_name.startswith(prefix + ".")
        for prefix in prefixes
    )


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_core_contracts_do_not_depend_on_outer_application_layers(self):
        core_roots = [ROOT / "kira" / name for name in ("core", "domain")]
        files = sorted(
            path
            for package_root in core_roots
            if package_root.is_dir()
            for path in package_root.rglob("*.py")
        )
        violations = []
        for path in files:
            for imported in _imported_modules(path):
                is_kira_package = imported == "kira" or imported.startswith("kira.")
                is_inner_layer = _matches_prefix(
                    imported, CORE_ALLOWED_PACKAGE_PREFIXES
                )
                if (is_kira_package and not is_inner_layer) or _matches_prefix(
                    imported, QT_IMPORT_PREFIXES
                ):
                    violations.append(
                        f"{path.relative_to(ROOT)} imports {imported}"
                    )
        self.assertEqual(
            violations,
            [],
            "Core/domain packages may import only Core/Domain packages and the standard library; "
            "all other kira packages are outer-layer dependencies.",
        )

    def test_chat_ui_calls_web_search_application_service_not_engine_module(self):
        ui_paths = (
            ROOT / "kira" / "ui" / "main_window_chat.py",
            ROOT / "kira" / "ui" / "main_window_chat_support.py",
        )
        violations = []
        for path in ui_paths:
            for imported in _imported_modules(path):
                if _matches_prefix(imported, ("kira.websearch",)):
                    violations.append(
                        f"{path.relative_to(ROOT)} imports {imported}"
                    )
        self.assertEqual(violations, [])
        chat_source = ui_paths[0].read_text(encoding="utf-8")
        self.assertNotIn("websearch.", chat_source)
        self.assertIn("self.web_search_service.plan_request(", chat_source)
        self.assertIn("self.web_search_service.format_evidence(", chat_source)

    def test_shared_event_bus_and_chat_publisher_depend_on_core_contracts(self):
        event_bus_imports = _imported_modules(ROOT / "kira" / "app" / "event_bus.py")
        chat_event_imports = _imported_modules(ROOT / "kira" / "chat" / "events.py")

        self.assertFalse(
            any(_matches_prefix(item, ("kira.chat",)) for item in event_bus_imports),
            "The shared EventBus must not import a concrete feature package.",
        )
        self.assertFalse(
            any(_matches_prefix(item, ("kira.app",)) for item in chat_event_imports),
            "Feature event publishers must depend on Core event-bus ports, not app implementations.",
        )

    def test_application_services_do_not_import_ui_or_qt(self):
        app_root = ROOT / "kira" / "app"
        files = sorted(
            path for path in app_root.rglob("*.py")
            if path.name != "bootstrap.py"
        )
        violations = []
        for path in files:
            for imported in _imported_modules(path):
                if _matches_prefix(imported, APPLICATION_FORBIDDEN_PREFIXES):
                    violations.append(
                        f"{path.relative_to(ROOT)} imports {imported}"
                    )
        self.assertEqual(
            violations,
            [],
            "Only the composition root may connect application services to the UI/Qt.",
        )


if __name__ == "__main__":
    unittest.main()
