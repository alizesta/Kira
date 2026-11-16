"""Qt-free architectural checks for the extracted chat application boundary."""
import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OLDMAIN = ROOT / "kira" / "oldmain.py"


class ChatApplicationWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = OLDMAIN.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)
        cls.main_window = next(
            node for node in cls.tree.body
            if isinstance(node, ast.ClassDef) and node.name == "MainWindow"
        )

    def method(self, name):
        return next(
            node for node in self.main_window.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
        )

    def test_main_window_passes_the_injected_history_service(self):
        init = self.method("__init__")
        calls = [
            node for node in ast.walk(init)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "ChatApplicationService"
        ]
        self.assertEqual(len(calls), 1)
        persistence = [kw.value for kw in calls[0].keywords if kw.arg == "persistence"]
        self.assertEqual(len(persistence), 1)
        self.assertIsInstance(persistence[0], ast.Name)
        self.assertEqual(persistence[0].id, "chat_history_service")

    def test_session_conversation_identity_flows_through_application_service(self):
        self.assertIn("self.chat_application_service.get_or_create_conversation(session.cid)", self.source)
        self.assertIn("conversation_id=self.cur.conversation_id", self.source)
        self.assertIn("self.cur.conversation_id", self.source)

    def test_main_window_does_not_import_chat_internal_components(self):
        self.assertNotIn("from .chat.coordinator import", self.source)
        self.assertNotIn("from .chat.context_builder import", self.source)
        self.assertNotIn("from .chat.response_handler import", self.source)
        self.assertNotIn("self.chat_history_service", self.source)
        self.assertIn("self.chat_application_service.submit_message", self.source)
        self.assertIn("self.chat_application_service.start_provider_request", self.source)

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
