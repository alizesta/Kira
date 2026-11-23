"""Optional application modules must not import their implementations at registration/startup."""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class OptionalServiceImportTests(unittest.TestCase):
    def test_optional_service_modules_remain_unimported_when_registered_and_started(self):
        code = """
import sys
from kira.app.dependency_container import DependencyContainer
from kira.app.event_bus import EventBus
from kira.app.feature_modules import register_application_modules
from kira.app.module_manager import ModuleManager

container = DependencyContainer()
event_bus = EventBus()
manager = ModuleManager(container, event_bus)
register_application_modules(
    manager,
    container,
    settings={},
    event_publisher=object(),
)
manager.start("coding_agent")
manager.start("brain_application")
manager.start("reflection_application")
forbidden = {
    "kira.app.coding_agent_application",
    "kira.app.brain_application",
    "kira.app.reflection_application",
}
loaded = forbidden.intersection(sys.modules)
manager.shutdown()
event_bus.close()
assert not loaded, sorted(loaded)
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
