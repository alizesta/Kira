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
manager.start("conversation_organization")
manager.start("chat_search")
manager.start("chat_transfer")
manager.start("web_search")
manager.start("shared_skills")
manager.start("coding_agent")
manager.start("brain_application")
manager.start("reflection_application")
forbidden = {
    "kira.app.coding_agent_application",
    "kira.app.brain_application",
    "kira.app.reflection_application",
    "kira.app.organization_application",
    "kira.app.chat_search_application",
    "kira.app.chat_transfer_application",
    "kira.app.web_search",
    "kira.app.shared_skills_application",
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


    def test_registration_does_not_import_feature_implementations(self):
        code = """
import sys
from kira.app.dependency_container import DependencyContainer
from kira.app.event_bus import EventBus
from kira.app.feature_modules import register_application_modules
from kira.app.module_manager import ModuleManager

container = DependencyContainer()
event_bus = EventBus()
manager = ModuleManager(container, event_bus)
register_application_modules(manager, container, settings={}, event_publisher=object())
forbidden = {
    "kira.services.character_service",
    "kira.services.chat_history_service",
    "kira.services.memory_service",
    "kira.services.mood_service",
    "kira.app.game_mode_application",
    "kira.app.provider_application",
    "kira.app.runtime_settings_application",
    "kira.app.vision_application",
    "kira.app.desktop_capture_application",
    "kira.app.desktop_context",
    "kira.app.chat_composition",
    "kira.app.session_composition",
    "kira.app.initiative_composition",
    "kira.app.voice_composition",
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



    def test_importing_one_service_does_not_import_the_other_service_modules(self):
        code = """
import importlib
import sys
importlib.import_module("kira.services.chat_history_service")
forbidden = {
    "kira.services.character_service",
    "kira.services.memory_service",
    "kira.services.mood_service",
}
loaded = forbidden.intersection(sys.modules)
assert not loaded, sorted(loaded)
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_legacy_package_level_service_exports_remain_lazy_and_compatible(self):
        code = """
import sys
from kira.services import SqliteChatHistoryService
assert SqliteChatHistoryService.__name__ == "SqliteChatHistoryService"
assert "kira.services.chat_history_service" in sys.modules
for name in ("kira.services.character_service", "kira.services.memory_service", "kira.services.mood_service"):
    assert name not in sys.modules, name
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)



if __name__ == "__main__":
    unittest.main()
