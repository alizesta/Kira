"""Architecture guards for the legacy application-policy migration."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
UI_ROOT = ROOT / "kira" / "ui"


class PolicyArchitectureTests(unittest.TestCase):
    def test_oldmain_is_removed_and_no_production_module_imports_it(self):
        self.assertFalse((ROOT / "kira" / "oldmain.py").exists())
        for path in (ROOT / "kira").rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("from .oldmain import", source, str(path))
            self.assertNotIn("from ..oldmain import", source, str(path))
            self.assertNotIn("import kira.oldmain", source, str(path))

    def test_provider_route_policy_and_router_construction_are_outside_ui(self):
        sources = "\n".join(
            path.read_text(encoding="utf-8")
            for path in UI_ROOT.glob("main_window*.py")
        )
        for forbidden in (
            "route_model.",
            "from .. import routes as route_model",
            "HybridRouter(",
            "OllamaClient.from_settings(",
            "api_manager.apply_models(",
            "api_manager.apply_failure(",
            "api_manager.set_model_enabled(",
            "api_manager.set_api_enabled(",
            "api_manager.delete_api(",
            "usage.install(",
            "evidence_memory.configure(",
            "self.tool_agent.set_settings(",
        ):
            self.assertNotIn(forbidden, sources)
        bootstrap = (ROOT / "kira" / "app" / "bootstrap.py").read_text(encoding="utf-8")
        self.assertIn("provider_application_service=provider_application_service", bootstrap)
        self.assertIn("runtime_settings_application_service=runtime_settings_application_service", bootstrap)
        self.assertIn("self.runtime_settings_application_service.apply(", sources)

    def test_vision_policy_and_frame_gate_are_outside_ui(self):
        sources = "\n".join(
            path.read_text(encoding="utf-8")
            for path in UI_ROOT.glob("main_window*.py")
        )
        for forbidden in ("FrameGate(", "policy_for(", "_vision_gate", "_vision_last_note"):
            self.assertNotIn(forbidden, sources)
        self.assertIn("self.vision_application_service.should_analyze(", sources)
        self.assertIn("self.vision_application_service.consume_result(", sources)

    def test_coding_agent_handoff_and_shutdown_are_outside_ui(self):
        sources = "\n".join(
            path.read_text(encoding="utf-8")
            for path in UI_ROOT.glob("main_window*.py")
        )
        self.assertIn("self.coding_agent_application_service.dispatch(", sources)
        self.assertIn("self.coding_agent_application_service.stop_session(", sources)
        self.assertNotIn("self.code_chat.handle(", sources)
        self.assertNotIn("self.code_chat.stop(", sources)
        self.assertNotIn("code_chat.stop(session)", sources)

    def test_application_policy_services_are_qt_free_and_bootstrap_injected(self):
        app_root = ROOT / "kira" / "app"
        for name in (
            "provider_application.py",
            "vision_application.py",
            "coding_agent_application.py",
            "runtime_settings_application.py",
            "session_application.py",
            "web_search.py",
            "voice_application.py",
            "game_mode_application.py",
        ):
            source = (app_root / name).read_text(encoding="utf-8")
            self.assertNotIn("PySide6", source, name)
        bootstrap = (app_root / "bootstrap.py").read_text(encoding="utf-8")
        for dependency in (
            "provider_application_service=provider_application_service",
            "vision_application_service=vision_application_service",
            "coding_agent_application_service=coding_agent_application_service",
            "tool_agent=tool_agent",
        ):
            self.assertIn(dependency, bootstrap)


if __name__ == "__main__":
    unittest.main()
