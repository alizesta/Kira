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

    def test_bootstrap_passes_the_injected_history_service(self):
        bootstrap = ast.parse((ROOT / "kira" / "app" / "bootstrap.py").read_text(encoding="utf-8"))
        calls = [
            node for node in ast.walk(bootstrap)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "create_chat_application_service_factory"
        ]
        self.assertEqual(len(calls), 1)
        persistence = [kw.value for kw in calls[0].keywords if kw.arg == "persistence"]
        self.assertEqual(len(persistence), 1)
        self.assertIsInstance(persistence[0], ast.Name)
        self.assertEqual(persistence[0].id, "chat_history_service")

    def test_bootstrap_injects_chat_service_factory_into_main_window(self):
        bootstrap = (ROOT / "kira" / "app" / "bootstrap.py").read_text(encoding="utf-8")
        composition = (ROOT / "kira" / "app" / "chat_composition.py").read_text(encoding="utf-8")
        self.assertIn("chat_application_service_factory", bootstrap)
        self.assertIn("create_chat_application_service_factory", bootstrap)
        self.assertIn("chat_application_service_factory(create_chat_application_ports(self))", self.source)
        self.assertIn("ChatApplicationService", composition)
        self.assertIn("_dispatch_application_request", composition + (ROOT / "kira" / "ui" / "application_adapters.py").read_text(encoding="utf-8"))

    def test_session_conversation_identity_flows_through_application_service(self):
        session_service = (ROOT / "kira" / "app" / "session_application.py").read_text(encoding="utf-8")
        self.assertIn("self.session_application_service.bind_conversation(session)", self.source)
        self.assertIn("get_or_create_conversation(session.cid)", session_service)
        self.assertIn("conversation_id=self.cur.conversation_id", self.source)
        self.assertIn("self.cur.conversation_id", self.source)

    def test_main_window_does_not_import_chat_internal_components(self):
        self.assertNotIn("from .chat.coordinator import", self.source)
        self.assertNotIn("from .chat.context_builder import", self.source)
        self.assertNotIn("from .chat.response_handler import", self.source)
        self.assertNotIn("self.chat_history_service", self.source)
        self.assertIn("self.chat_application_service.submit_message", self.source)
        self.assertIn("self.chat_application_service.start_provider_request", self.source)

    def test_session_manager_owns_runtime_lifecycle_and_request_identity(self):
        self.assertIn("session_manager or SessionManager(ChatSession)", self.source)
        self.assertIn("create_session_application_service_factory", self.source)
        self.assertIn("self.session_application_service.create_active_session(", self.source)
        self.assertIn("self.session_application_service.activate_session(sess.session_id)", self.source)
        self.assertIn("self.session_application_service.dispose()", self.source)
        self.assertNotIn("self.session_manager.create_session(", self.source)
        self.assertNotIn("self.session_manager.activate_session(", self.source)
        self.assertIn("self.session_manager.get_session(event.session_id)", self.source)
        self.assertIn("self.chat_application_service.submit_message(\n            self.cur.session_id", self.source)

    def test_shutdown_delegates_partial_response_cleanup_to_application_service(self):
        close_event = self.method("closeEvent")
        close_calls = [node for node in ast.walk(close_event) if isinstance(node, ast.Call)]
        close_methods = [
            node.func.attr for node in close_calls
            if isinstance(node.func, ast.Attribute)
        ]
        self.assertIn("_clear_chat_coordinator_queues", close_methods)
        self.assertNotIn("save_message", close_methods)

        cleanup = self.method("_clear_chat_coordinator_queues")
        cleanup_calls = [node for node in ast.walk(cleanup) if isinstance(node, ast.Call)]
        self.assertTrue(any(
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "dispose"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "chat_application_service"
            for node in cleanup_calls
        ))


if __name__ == "__main__":
    unittest.main()
