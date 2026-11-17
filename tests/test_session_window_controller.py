import unittest
from types import SimpleNamespace

from kira.app.session_controller import SessionWindowMixin


class _Window(SessionWindowMixin):
    def __init__(self):
        self.settings = {"active_character_id": "kira"}
        self.previous = SimpleNamespace(cid="kira")
        self.current = SimpleNamespace(cid="ren")
        self.cur = self.previous
        self.front = self.previous
        self.sessions = {"kira": self.previous}
        self.chat_application_service = SimpleNamespace(
            get_or_create_conversation=lambda character_id: {"id": f"conversation-{character_id}"}
        )


class SessionWindowMixinTests(unittest.TestCase):
    def test_session_context_restores_previous_session_and_character(self):
        window = _Window()

        with window._as(window.current):
            self.assertIs(window.cur, window.current)
            self.assertEqual(window.settings["active_character_id"], "ren")

        self.assertIs(window.cur, window.previous)
        self.assertEqual(window.settings["active_character_id"], "kira")

    def test_session_context_falls_back_to_front_when_previous_session_was_removed(self):
        window = _Window()
        window.front = window.current

        with window._as(window.current):
            window.sessions.clear()

        self.assertIs(window.cur, window.current)
        self.assertEqual(window.settings["active_character_id"], "kira")

    def test_conversation_binding_is_owned_by_session_controller(self):
        window = _Window()
        session = SimpleNamespace(cid="mika", conversation_id=None)

        result = window._ensure_session_conversation(session)

        self.assertEqual(result, "conversation-mika")
        self.assertEqual(session.conversation_id, "conversation-mika")

    def test_conversation_binding_degrades_safely_when_storage_is_unavailable(self):
        window = _Window()
        window.chat_application_service.get_or_create_conversation = lambda _cid: (_ for _ in ()).throw(
            RuntimeError("storage unavailable")
        )
        session = SimpleNamespace(cid="ren", conversation_id=None)

        self.assertIsNone(window._ensure_session_conversation(session))
        self.assertIsNone(session.conversation_id)

    def test_worker_running_probe_handles_deleted_qt_worker(self):
        class DeletedWorker:
            def isRunning(self):
                raise RuntimeError("wrapped C++ object has been deleted")

        self.assertFalse(SessionWindowMixin._worker_is_running(DeletedWorker()))
        self.assertFalse(SessionWindowMixin._worker_is_running(None))


if __name__ == "__main__":
    unittest.main()
