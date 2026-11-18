"""Architecture guards: Application and Core must not depend on desktop Qt."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INNER_ROOTS = (
    ROOT / "kira" / "app",
    ROOT / "kira" / "chat",
    ROOT / "kira" / "core" / "interfaces",
)
QT_MODULE_PREFIXES = ("PySide", "PyQt")
QT_RUNTIME_NAMES = {
    "QApplication", "QCoreApplication", "QWidget", "QMainWindow",
    "QObject", "QThread", "QTimer", "Signal", "Slot",
}


class ApplicationQtIndependenceTests(unittest.TestCase):
    def test_inner_layers_do_not_import_qt_bindings(self):
        violations = []
        for root in INNER_ROOTS:
            for path in root.rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        modules = [alias.name for alias in node.names]
                    elif isinstance(node, ast.ImportFrom):
                        modules = [node.module or ""]
                    else:
                        continue
                    for module in modules:
                        if module.startswith(QT_MODULE_PREFIXES):
                            violations.append(f"{path.relative_to(ROOT)}:{node.lineno}: {module}")
        self.assertEqual(violations, [])

    def test_inner_layers_do_not_reference_qt_runtime_types(self):
        violations = []
        for root in INNER_ROOTS:
            for path in root.rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Name) and node.id in QT_RUNTIME_NAMES:
                        violations.append(f"{path.relative_to(ROOT)}:{node.lineno}: {node.id}")
        self.assertEqual(violations, [])

    def test_chat_dispatcher_uses_provider_worker_port_not_qt_signals(self):
        path = ROOT / "kira" / "chat" / "coordinator.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        source = path.read_text(encoding="utf-8")
        self.assertIn("ProviderWorkerPort", source)
        self.assertIn("worker.subscribe(event_name, callback)", source)
        self.assertNotIn(".connect(callback)", source)
        self.assertNotIn("finished_ok", source)
        self.assertNotIn("isRunning", source)

    def test_voice_service_uses_speaker_and_listener_ports(self):
        path = ROOT / "kira" / "app" / "voice_application.py"
        source = path.read_text(encoding="utf-8")
        self.assertIn("SpeakerPort", source)
        self.assertIn("VoiceListenerPort", source)
        self.assertIn('listener.subscribe("heard"', source)
        self.assertIn("listener.is_running()", source)
        self.assertNotIn(".connect(", source)
        self.assertNotIn("isRunning", source)
        self.assertNotIn("begin_kira_speech", source)
        self.assertNotIn('getattr(self.speaker, "_began"', source)


if __name__ == "__main__":
    unittest.main()
