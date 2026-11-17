"""Qt-free architectural checks for the extracted chat application boundary."""
import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI_ROOT = ROOT / "kira" / "ui"
WINDOW_FILES = tuple(sorted(UI_ROOT.glob("main_window*.py")))


class ChatApplicationWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = {
            path: path.read_text(encoding="utf-8")
            for path in WINDOW_FILES
        }
        cls.source = "\n".join(cls.sources.values())
        cls.chat_source = (UI_ROOT / "main_window_chat.py").read_text(encoding="utf-8")
        cls.trees = {
            path: ast.parse(source, filename=str(path))
            for path, source in cls.sources.items()
        }
        cls.methods = {}
        for tree in cls.trees.values():
            for node in tree.body:
                if not isinstance(node, ast.ClassDef):
                    continue
                for member in node.body:
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        cls.methods.setdefault(member.name, member)

    def method(self, name):
        try:
            return self.methods[name]
        except KeyError as exc:
            self.fail(f"MainWindow feature mixins do not define {name!r}")

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

    def test_bootstrap_injects_chat_service_factory_into_main_window(self):
        bootstrap = (ROOT / "kira" / "app" / "bootstrap.py").read_text(encoding="utf-8")
        composition = (ROOT / "kira" / "app" / "chat_composition.py").read_text(encoding="utf-8")
        self.assertIn("session_application_service_factory", bootstrap)
        self.assertIn("create_session_application_service_factory", bootstrap)
        self.assertIn("session_application_service_factory", self.source)
        self.assertIn("chat_application_service_factory", bootstrap)
        self.assertIn("web_search_service=web_search_service", bootstrap)
        self.assertIn("create_chat_application_service_factory", bootstrap)
        self.assertIn("chat_application_service_factory(self)", self.source)
        self.assertIn("ChatApplicationService", composition)
        self.assertIn("window._dispatch_application_request", composition)

    def test_session_conversation_identity_flows_through_application_service(self):
        service = (ROOT / "kira" / "app" / "session_application.py").read_text(encoding="utf-8")
        self.assertIn("self.chat_application_service.get_or_create_conversation(session.cid)", service)
        self.assertIn("self.session_application_service.bind_conversation(session)", self.source)
        self.assertIn("conversation_id=self.cur.conversation_id", self.source)
        self.assertIn("self.cur.conversation_id", self.source)

    def test_web_search_policy_is_owned_by_injected_application_service(self):
        bootstrap = (ROOT / "kira" / "app" / "bootstrap.py").read_text(encoding="utf-8")
        service = (ROOT / "kira" / "app" / "web_search.py").read_text(encoding="utf-8")
        self.assertIn("WebSearchApplicationService()", bootstrap)
        self.assertIn("self.web_search_service.web_search_options", self.chat_source)
        self.assertIn("self.web_search_service.image_search_options", self.chat_source)
        self.assertIn("def web_search_options(", service)
        self.assertIn("def merge_search_content(", service)
        self.assertNotIn("generativelanguage", self.chat_source)
        self.assertNotIn("websearch.is_followup", self.chat_source)
        self.assertNotIn("def make_search_query(", self.chat_source)
        self.assertNotIn("def make_image_query(", self.chat_source)

    def test_voice_lifecycle_is_owned_by_injected_application_service(self):
        bootstrap = (ROOT / "kira" / "app" / "bootstrap.py").read_text(encoding="utf-8")
        service = (ROOT / "kira" / "app" / "voice_application.py").read_text(encoding="utf-8")
        runtime = (UI_ROOT / "main_window_runtime.py").read_text(encoding="utf-8")
        self.assertIn("create_voice_application_service_factory", bootstrap)
        self.assertIn("voice_application_service_factory=voice_service_factory", bootstrap)
        self.assertIn("self.voice_application_service = voice_application_service_factory", self.source)
        for method in (
            "start_recording", "stop_recording", "speak", "stop_speaking",
            "stream_reset", "stream_text", "stream_end", "play_file", "is_speaking",
        ):
            self.assertIn(f"def {method}(", service)
        self.assertIn("self.voice_application_service.start_recording()", runtime)
        self.assertIn("self.voice_application_service.stop_recording()", runtime)
        self.assertIn("self.voice_application_service.speak(", self.source)
        self.assertIn("self.voice_application_service.stream_text(", self.source)
        self.assertIn('voice_application_service = front_only_property("voice_application_service")', self.source)
        self.assertNotIn("self.speaker.speak(", self.source)
        self.assertNotIn("self.speaker.stream_text(", self.source)
        self.assertNotIn("self.listener = Listener(", runtime)
        self.assertNotIn("PySide6", service)
        self.assertIn("self.voice_application_service.interpret_transcript(", runtime)
        self.assertNotIn("WAKE_RE", runtime)
        self.assertNotIn("STOP_RE", runtime)
        self.assertNotIn("SLEEP_RE", runtime)

    def test_game_mode_permissions_are_owned_by_application_service(self):
        bootstrap = (ROOT / "kira" / "app" / "bootstrap.py").read_text(encoding="utf-8")
        service = (ROOT / "kira" / "app" / "game_mode_application.py").read_text(encoding="utf-8")
        vision = (UI_ROOT / "main_window_attachments_vision.py").read_text(encoding="utf-8")
        runtime = (UI_ROOT / "main_window_runtime.py").read_text(encoding="utf-8")
        support = (UI_ROOT / "main_window_support.py").read_text(encoding="utf-8")
        self.assertIn("GameModeApplicationService()", bootstrap)
        self.assertIn("game_mode_application_service=game_mode_application_service", bootstrap)
        self.assertIn("self.game_mode_application_service.permissions(", vision)
        self.assertIn("self.game_mode_application_service.command_denial_reason(", runtime)
        self.assertNotIn("game_mode_policy", support)
        self.assertNotIn("game_mode_permissions(", vision)
        self.assertNotIn("COMPETITIVE_SAFE_MODE", runtime)
        self.assertIn("self.game_mode_application_service.classify_game_audio(", vision)
        self.assertNotIn("is_important_game_audio(", vision)
        self.assertNotIn("self._game_audio_alerts", vision)
        self.assertIn("def classify_game_audio(", service)

    def test_main_window_does_not_import_chat_internal_components(self):
        self.assertNotIn("from .chat.coordinator import", self.source)
        self.assertNotIn("from .chat.context_builder import", self.source)
        self.assertNotIn("from .chat.response_handler import", self.source)
        self.assertNotIn("self.chat_history_service", self.source)
        self.assertIn("self.chat_application_service.submit_message", self.source)
        self.assertIn("self.chat_application_service.start_provider_request", self.source)

    def test_session_manager_owns_runtime_lifecycle_and_request_identity(self):
        self.assertIn("session_manager or SessionManager(ChatSession)", self.source)
        session_service = (ROOT / "kira" / "app" / "session_application.py").read_text(encoding="utf-8")
        self.assertIn("self.session_manager.create_session(", session_service)
        self.assertIn("self.session_manager.activate_session(self.cur.session_id)", self.source)
        self.assertIn("self.session_manager.get_session(event.session_id)", self.source)
        self.assertIn("self.session_application_service.sync_sessions(", self.source)
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
