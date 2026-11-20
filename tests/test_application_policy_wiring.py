"""Qt-free guards for application policy ownership in the desktop adapters."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def source(path):
    return (ROOT / path).read_text(encoding="utf-8")


class ApplicationPolicyWiringTests(unittest.TestCase):
    def test_session_mixin_delegates_lifecycle_policy(self):
        ui = source("kira/ui/main_window_session.py")
        composition = source("kira/ui/main_window_composition.py")
        runtime = source("kira/ui/main_window_runtime.py")
        self.assertIn("self.context.services.session_application_service.ensure_session(", ui)
        self.assertIn("self.context.services.session_application_service.sync_sessions(", ui)
        self.assertIn("self.context.services.session_application_service.activate_session(", ui)
        self.assertIn("session_application_service_factory", composition)
        self.assertIn("self.context.services.session_application_service.dispose()", runtime)
        for forbidden in (
            "self.session_manager.create_session(",
            "self.session_manager.activate_session(",
            "self.session_manager.reopen_session(",
            "self.session_manager.close_session(",
        ):
            self.assertNotIn(forbidden, ui + composition + runtime)

    def test_provider_mutations_are_owned_by_provider_application_service(self):
        ui = "".join(
            source(path)
            for path in (
                "kira/ui/main_window_provider_settings.py",
                "kira/ui/main_window_lifecycle.py",
                "kira/ui/main_window_voice_settings.py",
            )
        )
        self.assertIn("self.context.services.provider_application_service.add_provider(", ui)
        self.assertIn("self.context.services.provider_application_service.rebuild_session_routers(", ui)
        runtime = source("kira/ui/main_window_runtime.py")
        self.assertIn("self.context.services.provider_application_service.find_route(", runtime)
        self.assertIn("self.context.services.provider_application_service.set_manual_route(", runtime)
        self.assertNotIn("route_model.", runtime)
        self.assertNotIn("OllamaClient.from_settings(", ui)

    def test_vision_capture_and_result_policy_are_application_owned(self):
        ui = source("kira/ui/main_window_attachments_vision.py")
        self.assertIn("self.context.services.vision_application_service.capture_allowed(", ui)
        self.assertIn("self.context.services.vision_application_service.should_analyze(", ui)
        self.assertIn("self.context.services.vision_application_service.consume_result(", ui)
        self.assertNotIn("_vision_gate", ui)
        self.assertNotIn("_vision_last_note", ui)
        self.assertNotIn("policy_for(", ui)
        self.assertNotIn("FrameGate(", ui)

    def test_coding_agent_handoff_and_stop_are_application_owned(self):
        chat = source("kira/ui/main_window_chat.py")
        vision = source("kira/ui/main_window_attachments_vision.py")
        self.assertIn("self.context.services.coding_agent_application_service.dispatch(", chat)
        self.assertIn("self.context.services.coding_agent_application_service.stop_session(", chat + vision)
        self.assertNotIn("self.code_chat.handle(", chat)
        self.assertNotIn("self.code_chat.stop(", chat + vision)

    def test_global_runtime_reconfiguration_is_application_owned(self):
        ui = source("kira/ui/main_window_lifecycle.py")
        self.assertIn("self.context.services.runtime_settings_application_service.apply(", ui)
        self.assertNotIn("self.tool_agent.set_settings(", ui)
        self.assertNotIn("evidence_memory.configure(", ui)
        self.assertNotIn("usage.install(", ui)

    def test_runtime_settings_are_configured_once_at_composition(self):
        composition = source("kira/ui/main_window_composition.py")
        self.assertEqual(
            composition.count("runtime_settings_application_service.configure(self.services.settings)"),
            1,
        )
        lifecycle = source("kira/ui/main_window_lifecycle.py")
        self.assertIn("self.context.services.runtime_settings_application_service.apply(", lifecycle)

    def test_tool_task_presence_is_scoped_to_the_active_character(self):
        chat = source("kira/ui/main_window_chat.py")
        self.assertIn("self.context.services.tool_agent.tasks.active(self.context.state.cur.cid) is not None", chat)
        self.assertNotIn("self.tool_agent.tasks.active() is not None", chat)

    def test_character_profile_and_voice_mutations_are_service_owned(self):
        ui = source("kira/ui/main_window_character_settings.py")
        self.assertIn("self.context.services.character_service.create_profile(", ui)
        self.assertIn("self.context.services.character_service.update_profile(", ui)
        self.assertIn("self.context.services.character_service.delete_profile(", ui)
        self.assertIn("self.context.services.character_service.save_preferences(", ui)
        self.assertIn("self.context.services.character_service.save_personality(", ui)
        self.assertIn("self.context.services.voice_application_service.apply_character_settings(", ui)
        self.assertNotIn('self.settings.setdefault("characters", [])', ui)
        self.assertNotIn('self.settings["characters"] =', ui)


if __name__ == "__main__":
    unittest.main()
