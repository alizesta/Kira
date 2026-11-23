"""Qt-free architectural checks for the extracted chat application boundary."""
import ast
import unittest
from pathlib import Path

from tests.ui_helpers import main_window_source, window_method_node


ROOT = Path(__file__).resolve().parents[1]


class ChatApplicationWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = main_window_source()

    def method(self, name):
        return window_method_node(name)

    def test_feature_graph_binds_the_injected_history_service(self):
        modules = ast.parse((ROOT / "kira" / "app" / "feature_modules.py").read_text(encoding="utf-8"))
        calls = [
            node for node in ast.walk(modules)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "create_chat_application_service_factory"
        ]
        self.assertEqual(len(calls), 1)
        persistence = [kw.value for kw in calls[0].keywords if kw.arg == "persistence"]
        self.assertEqual(len(persistence), 1)
        self.assertIsInstance(persistence[0], ast.Call)
        self.assertIsInstance(persistence[0].func, ast.Attribute)
        self.assertEqual(persistence[0].func.attr, "resolve")
        self.assertEqual(persistence[0].args[0].value, "chat_history_service")

    def test_ui_composition_receives_bootstrap_owned_chat_factory(self):
        bootstrap = (ROOT / "kira" / "ui" / "bootstrap.py").read_text(encoding="utf-8")
        composition = (ROOT / "kira" / "app" / "chat_composition.py").read_text(encoding="utf-8")
        self.assertIn('chat_application_service_factory=container.resolve("chat_application_service_factory")', bootstrap)
        self.assertIn("chat_application_service_factory(create_chat_application_ports(self))", self.source)
        self.assertIn("ChatApplicationService", composition)
        self.assertIn("_dispatch_application_request", self.source + (ROOT / "kira" / "ui" / "application_adapters.py").read_text(encoding="utf-8"))

    def test_session_conversation_identity_flows_through_application_service(self):
        session_service = (ROOT / "kira" / "app" / "session_application.py").read_text(encoding="utf-8")
        self.assertIn("self.context.services.session_application_service.bind_conversation(session)", self.source)
        self.assertIn("get_or_create_conversation(session.cid)", session_service)
        self.assertIn("conversation_id=self.context.state.cur.conversation_id", self.source)
        self.assertIn("self.context.state.cur.conversation_id", self.source)

    def test_main_window_does_not_import_chat_internal_components(self):
        self.assertNotIn("from .chat.coordinator import", self.source)
        self.assertNotIn("from .chat.context_builder import", self.source)
        self.assertNotIn("from .chat.response_handler import", self.source)
        self.assertNotIn("self.chat_history_service", self.source)
        self.assertIn("self.context.services.chat_application_service.submit_message", self.source)
        self.assertIn("self.context.services.chat_application_service.start_provider_request", self.source)

    def test_session_manager_is_created_at_the_outer_composition_root(self):
        bootstrap = (ROOT / "kira" / "ui" / "bootstrap.py").read_text(encoding="utf-8")
        modules = (ROOT / "kira" / "app" / "feature_modules.py").read_text(encoding="utf-8")
        self.assertIn("session_manager = SessionManager(ChatSession)", bootstrap)
        self.assertIn("session_manager=session_manager", bootstrap)
        self.assertIn('session_application_service_factory=container.resolve("session_application_service_factory")', bootstrap)
        self.assertIn("self.services.session_manager = session_manager", self.source)
        self.assertNotIn("session_manager or SessionManager(ChatSession)", self.source)
        self.assertIn("session_application_service_factory", modules)
        self.assertIn("session_application_service_factory(", self.source)
        self.assertIn("self.services.session_application_service.create_active_session(", self.source)
        self.assertIn("self.context.services.session_application_service.activate_session(sess.session_id)", self.source)
        self.assertIn("self.context.services.session_application_service.dispose()", self.source)
        self.assertNotIn("self.session_manager.create_session(", self.source)
        self.assertNotIn("self.session_manager.activate_session(", self.source)
        self.assertIn("self.context.services.session_manager.get_session(event.session_id)", self.source)
        self.assertIn("self.context.services.chat_application_service.submit_message(\n            self.context.state.cur.session_id", self.source)

    def test_attachment_composition_and_limits_do_not_leak_into_chat_ui(self):
        chat = (ROOT / "kira" / "ui" / "main_window_chat.py").read_text(encoding="utf-8")
        support = (ROOT / "kira" / "ui" / "main_window_chat_support.py").read_text(encoding="utf-8")
        service = (ROOT / "kira" / "chat" / "application_service.py").read_text(encoding="utf-8")
        self.assertIn("self.context.services.chat_application_service.max_attachments", chat)
        self.assertIn("self.context.services.chat_application_service.compose_attachments(", chat)
        self.assertNotIn("att.MAX_FILES", chat)
        self.assertNotIn("att.compose(", chat)
        self.assertNotIn("from ..chat import attachments as att", support)
        self.assertIn("def compose_attachments(", service)
        self.assertIn("def max_attachments(", service)


    def test_eye_mode_chat_uses_rolling_context_without_per_turn_screenshot(self):
        chat = (ROOT / "kira" / "ui" / "main_window_chat.py").read_text(encoding="utf-8")
        vision = (ROOT / "kira" / "ui" / "main_window_attachments_vision.py").read_text(encoding="utf-8")
        self.assertNotIn('._live_vision_attachment()', chat)
        self.assertIn('build_chat_vision_context(', chat)
        self.assertIn('"visual_observation"', vision)
        self.assertIn('context_service.record_event(', vision)
        self.assertIn('recent timestamped visual observations', vision)
        self.assertIn('selected_monitor_frame_is_independent_of_foreground_window', vision)
        self.assertIn('desktop_source_active and current is not None and desktop_allowed', vision)
        self.assertIn('("desktop-monitor", str(privacy.selected_monitor_id or "auto"))', vision)
        self.assertIn('(source == "game" and latest_identity != foreground_identity)', vision)
        self.assertNotIn('self._capture_desktop_frame()', vision[vision.index("    def _vision_status"):vision.index("    def build_chat_vision_context")])

    def test_shutdown_uses_two_phase_chat_application_disposal(self):
        runtime_tree = ast.parse((ROOT / "kira" / "ui" / "main_window_runtime.py").read_text(encoding="utf-8"))
        runtime_methods = {n.name: n for n in ast.walk(runtime_tree) if isinstance(n, ast.FunctionDef)}
        close_event = runtime_methods["closeEvent"]
        close_calls = [node for node in ast.walk(close_event) if isinstance(node, ast.Call)]
        close_methods = [
            node.func.attr for node in close_calls
            if isinstance(node.func, ast.Attribute)
        ]
        self.assertIn("_clear_chat_coordinator_queues", close_methods)
        self.assertNotIn("save_message", close_methods)

        begin_shutdown = runtime_methods["_clear_chat_coordinator_queues"]
        begin_calls = [node for node in ast.walk(begin_shutdown) if isinstance(node, ast.Call)]
        self.assertTrue(any(
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "begin_shutdown"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "chat_application_service"
            for node in begin_calls
        ))

        final_dispose = runtime_methods["_dispose_chat_application_service"]
        dispose_calls = [node for node in ast.walk(final_dispose) if isinstance(node, ast.Call)]
        self.assertTrue(any(
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "dispose"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "chat_application_service"
            for node in dispose_calls
        ))


if __name__ == "__main__":
    unittest.main()
