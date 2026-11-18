"""Architecture regression tests for the production Composition Root."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def parse(path: str) -> ast.Module:
    return ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=path)


class CompositionRootContractTests(unittest.TestCase):
    def test_qt_composition_root_is_outside_application_package(self):
        self.assertTrue((ROOT / "kira" / "ui" / "bootstrap.py").is_file())
        self.assertFalse((ROOT / "kira" / "app" / "bootstrap.py").exists())

    def test_window_composition_requires_bootstrap_owned_dependencies(self):
        module = parse("kira/ui/main_window_composition.py")
        function = next(
            node for node in module.body
            if isinstance(node, ast.FunctionDef) and node.name == "initialize_main_window"
        )
        required = next(
            node.value for node in ast.walk(function)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "required" for target in node.targets)
        )
        keys = {key.value for key in required.keys if isinstance(key, ast.Constant)}
        self.assertTrue({
            "memory_service", "mood_service", "character_service",
            "chat_event_publisher", "chat_application_service_factory",
            "session_manager", "session_application_service_factory",
            "web_search_service", "voice_application_service_factory",
            "game_mode_application_service", "settings", "tool_agent",
            "provider_application_service", "coding_agent_application_service",
            "vision_application_service", "runtime_settings_application_service",
            "shared_skills_application_service",
        }.issubset(keys))

    def test_ui_composition_does_not_construct_application_services(self):
        module = parse("kira/ui/main_window_composition.py")
        forbidden_imports = []
        for node in ast.walk(module):
            if isinstance(node, ast.ImportFrom) and node.module and (
                node.module.startswith("..app.") or node.module.startswith("..services.")
            ):
                forbidden_imports.append(node.module)
        self.assertEqual(forbidden_imports, [])

        forbidden_calls = {
            "PersonaMemoryService", "MoodStateService", "CharacterProfileService",
            "SqliteChatHistoryService", "WebSearchApplicationService",
            "GameModeApplicationService", "ProviderApplicationService",
            "CodingAgentApplicationService", "VisionApplicationService", "ToolAgent",
            "SessionManager", "ChatSession",
        }
        constructed = {
            node.func.id for node in ast.walk(module)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertFalse(forbidden_calls & constructed)

    def test_bootstrap_owns_runtime_tool_agent_and_injects_it(self):
        module = parse("kira/ui/bootstrap.py")
        calls = [
            node for node in ast.walk(module)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        self.assertIn("ToolAgent", {node.func.id for node in calls})
        main_window_calls = [
            node for node in calls if node.func.id == "MainWindow"
        ]
        self.assertEqual(len(main_window_calls), 1)
        keywords = {item.arg for item in main_window_calls[0].keywords}
        self.assertIn("tool_agent", keywords)
        self.assertIn("session_manager", keywords)


if __name__ == "__main__":
    unittest.main()
