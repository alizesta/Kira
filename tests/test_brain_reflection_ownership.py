"""Regression tests for Brain/Reflection ownership and UI dependency direction."""
from __future__ import annotations
import ast
from pathlib import Path
import unittest
from unittest.mock import Mock
from kira.app.brain_application import BrainApplicationService
from kira.app.reflection_application import ReflectionApplicationService

ROOT = Path(__file__).resolve().parents[1]

class BrainReflectionServiceTests(unittest.TestCase):
    def test_brain_service_delegates_planning_prompt_and_reset(self):
        engine = Mock()
        decision = object()
        engine.decide.return_value = decision
        engine.Decision.return_value = "default"
        engine.extend_prompt.return_value = "prompt+brain"
        service = BrainApplicationService(engine)
        self.assertIs(service.decide("analyze", settings={}), decision)
        self.assertEqual(service.default_decision(), "default")
        self.assertEqual(service.extend_prompt("prompt", decision), "prompt+brain")
        service.reset_state("ren")
        service.status("ren")
        engine.decide.assert_called_once_with("analyze", None, None, False, False, {})
        engine.extend_prompt.assert_called_once_with("prompt", decision, None, None, character_id=None)
        engine.reset_state.assert_called_once_with("ren")
        engine.status.assert_called_once_with("ren")

    def test_reflection_service_delegates_completed_turn_once(self):
        engine = Mock()
        engine.after_turn.return_value = {"stage": "deep"}
        service = ReflectionApplicationService(engine)
        result = service.after_turn("router", {"brain_reflection": "rules"}, "decision", "question", "answer",
                                    [{"name": "tool"}], "task", True, character_id="mika")
        self.assertEqual(result, {"stage": "deep"})
        engine.after_turn.assert_called_once_with("router", {"brain_reflection": "rules"}, "decision", "question",
                                                  "answer", [{"name": "tool"}], "task", True, character_id="mika")

    def test_ui_controllers_do_not_import_legacy_brain_backend(self):
        offenders = []
        for path in sorted((ROOT / "kira" / "ui").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module in {"brain", "..brain"}:
                    offenders.append(f"{path.name}:{node.lineno}")
                elif isinstance(node, ast.Import) and any(alias.name in {"kira.brain", "brain"} for alias in node.names):
                    offenders.append(f"{path.name}:{node.lineno}")
        self.assertEqual(offenders, [])

    def test_core_contract_has_no_application_or_ui_imports(self):
        source = (ROOT / "kira" / "core" / "interfaces" / "brain.py").read_text(encoding="utf-8")
        self.assertNotIn("kira.app", source)
        self.assertNotIn("kira.ui", source)
        self.assertNotIn("PySide", source)

    def test_application_services_are_registered_and_injected(self):
        from kira.app.dependency_container import DependencyContainer
        from kira.app.event_bus import EventBus
        from kira.app.feature_modules import register_application_modules
        from kira.app.module_manager import ModuleManager, ModuleState
        container, bus = DependencyContainer(), EventBus()
        manager = ModuleManager(container, bus)
        try:
            ids = register_application_modules(manager, container, settings={}, event_publisher=object())
            self.assertIn("brain_application", ids)
            self.assertIn("reflection_application", ids)
            manager.start("reflection_application")
            self.assertEqual(manager.state("brain_application"), ModuleState.STARTED)
            self.assertIsInstance(container.resolve("brain_application_service"), BrainApplicationService)
            self.assertIsInstance(container.resolve("reflection_application_service"), ReflectionApplicationService)
        finally:
            manager.shutdown()
            bus.close()

if __name__ == "__main__":
    unittest.main()
