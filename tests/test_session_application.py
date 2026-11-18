"""Qt-free tests for application-owned character Session orchestration."""
import unittest
from types import SimpleNamespace

from kira.chat.session_manager import SessionManager
from kira.chat_sessions import ChatSession
from kira.app.session_application import SessionApplicationService


class _ChatApplication:
    def __init__(self):
        self.active = set()
        self.pending = set()
        self.created = []

    def get_or_create_conversation(self, character_id):
        self.created.append(character_id)
        return {"id": f"conversation-{character_id}"}

    def has_active_request(self, session_id):
        return session_id in self.active

    def has_pending_work(self, session_id):
        return session_id in self.pending


class _Publisher:
    def __init__(self):
        self.events = []

    def publish(self, event_type, **payload):
        self.events.append((event_type, payload))


class SessionApplicationServiceTests(unittest.TestCase):
    def setUp(self):
        self.manager = SessionManager(ChatSession)
        self.chat = _ChatApplication()
        self.publisher = _Publisher()
        self.service = SessionApplicationService(self.manager, self.chat, self.publisher)

    def test_create_active_session_and_switch_activation_are_application_owned(self):
        first = self.service.create_active_session("kira")
        self.assertIs(self.manager.get_active_session(), first)

        second = self.service.ensure_session(
            "ren", {"name": "Ren"}, ensure_resources=lambda _session, _profile: None
        )
        self.assertTrue(self.service.activate_session(second.session_id))
        self.assertIs(self.manager.get_active_session(), second)
        self.assertEqual(first.status, "idle")
        self.assertEqual(second.status, "active")

    def test_dispose_releases_session_event_subscription(self):
        self.assertIsNotNone(self.service._unsubscribe)
        self.assertTrue(self.service.dispose())
        self.assertIsNone(self.service._unsubscribe)
        self.assertTrue(self.manager.is_disposed)

    def test_ensure_session_creates_runtime_session_and_binds_durable_conversation(self):
        resources = []
        session = self.service.ensure_session(
            "Mika",
            {"name": "Mika"},
            ensure_resources=lambda item, profile: resources.append((item, profile)),
        )

        self.assertEqual(session.cid, "mika")
        self.assertEqual(session.conversation_id, "conversation-mika")
        self.assertEqual(self.chat.created, ["mika"])
        self.assertEqual(resources, [(session, {"name": "Mika"})])

    def test_conversation_binding_preserves_existing_id_and_degrades_on_storage_error(self):
        existing = SimpleNamespace(cid="ren", conversation_id="existing")
        self.assertEqual(self.service.bind_conversation(existing), "existing")
        self.assertEqual(self.chat.created, [])

        self.chat.get_or_create_conversation = lambda _cid: (_ for _ in ()).throw(
            RuntimeError("storage unavailable")
        )
        missing = SimpleNamespace(cid="ren", conversation_id=None)
        self.assertIsNone(self.service.bind_conversation(missing))

    def test_state_transitions_are_published_as_application_events(self):
        session = self.manager.create_session("kira")
        self.manager.activate_session(session.session_id)

        self.assertEqual(
            [name for name, _payload in self.publisher.events],
            ["session_created", "session_activated"],
        )

    def test_sync_restores_each_profile_once_and_publishes_history_loaded(self):
        restored = []
        resources = []
        profiles = {
            "custom": {"name": "Custom"},
            "ren": {"name": "Ren"},
            "kira": {"name": "Kira"},
        }

        first = self.service.sync_sessions(
            profiles,
            ensure_resources=lambda session, profile: resources.append(session.cid),
            restore_history=lambda session: restored.append(session.cid),
        )
        second = self.service.sync_sessions(
            profiles,
            ensure_resources=lambda session, profile: resources.append(session.cid),
            restore_history=lambda session: restored.append(session.cid),
        )

        self.assertEqual(first, ("kira", "ren", "custom"))
        self.assertEqual(second, first)
        self.assertEqual(restored, ["kira", "ren", "custom"])
        self.assertEqual(resources.count("kira"), 2)
        self.assertEqual(
            [name for name, _payload in self.publisher.events],
            ["history_loaded", "history_loaded", "history_loaded"],
        )

    def test_history_restore_failure_does_not_mark_session_loaded_and_retries(self):
        session = self.manager.create_session("kira")
        attempts = []

        def restore_history(target):
            attempts.append(target.session_id)
            if len(attempts) == 1:
                raise RuntimeError("temporary database failure")
            return True

        for _ in range(2):
            self.service.sync_sessions(
                {"kira": {"name": "Kira"}},
                ensure_resources=lambda _session, _profile: None,
                restore_history=restore_history,
            )
            if not session.loaded:
                self.assertNotIn(
                    "history_loaded",
                    [name for name, _payload in self.publisher.events],
                )

        self.assertEqual(attempts, [session.session_id, session.session_id])
        self.assertTrue(session.loaded)
        self.assertEqual(
            [name for name, _payload in self.publisher.events].count("history_loaded"),
            1,
        )

    def test_history_restore_can_explicitly_defer_session_loading(self):
        session = self.manager.create_session("ren")
        self.service.sync_sessions(
            {"ren": {"name": "Ren"}},
            ensure_resources=lambda _session, _profile: None,
            restore_history=lambda _session: False,
        )
        self.assertFalse(session.loaded)
        self.assertNotIn(
            "history_loaded",
            [name for name, _payload in self.publisher.events],
        )

        self.service.sync_sessions(
            {"ren": {"name": "Ren"}},
            ensure_resources=lambda _session, _profile: None,
            restore_history=lambda _session: True,
        )
        self.assertTrue(session.loaded)
        self.assertEqual(
            [name for name, _payload in self.publisher.events].count("history_loaded"),
            1,
        )

    def test_deleted_character_session_is_retained_while_work_is_pending(self):
        session = self.manager.create_session("deleted")
        session.busy = True

        self.service.sync_sessions(
            {"kira": {}},
            ensure_resources=lambda _session, _profile: None,
            restore_history=lambda _session: None,
        )
        self.assertIs(self.manager.get_session(session.session_id), session)

        session.busy = False
        self.service.sync_sessions(
            {"kira": {}},
            ensure_resources=lambda _session, _profile: None,
            restore_history=lambda _session: None,
        )
        self.assertIsNone(self.manager.get_session(session.session_id))

    def test_pending_work_checks_application_queue_workers_and_vision(self):
        session = self.manager.create_session("kira")
        self.assertFalse(self.service.has_pending_work(session))

        self.chat.pending.add(session.session_id)
        self.assertTrue(self.service.has_pending_work(session))
        self.chat.pending.clear()

        session.worker = SimpleNamespace(isRunning=lambda: True)
        self.assertTrue(self.service.has_pending_work(session))
        session.worker = None

        session._vision_session = session
        session._vision_worker = SimpleNamespace(isRunning=lambda: True)
        self.assertTrue(self.service.has_pending_work(session))

        # Vision work belongs to its ChatSession; another session must not
        # inherit the active window's worker state.
        other = self.manager.create_session("ren")
        self.assertFalse(self.service.has_pending_work(other))

    def test_active_application_request_prevents_session_drain(self):
        session = self.manager.create_session("kira")
        self.chat.active.add(session.session_id)
        self.assertTrue(self.service.has_pending_work(session))
        self.chat.active.clear()
        self.assertFalse(self.service.has_pending_work(session))

    def test_closing_session_is_reopened_for_a_restored_character(self):
        session = self.manager.create_session("ren")
        self.manager.set_runtime_callbacks(has_pending_work=lambda _session: True)
        self.assertFalse(self.manager.close_session(session.session_id))
        self.assertEqual(session.status, "closing")

        ensured = self.service.ensure_session(
            "ren", {"name": "Ren"}, ensure_resources=lambda _session, _profile: None
        )

        self.assertIs(ensured, session)
        self.assertEqual(session.status, "idle")
        self.assertIs(self.manager.get_session_for_character("ren"), session)

    def test_failed_session_is_closed_and_replaced(self):
        failed = self.manager.create_session("mika")
        self.assertTrue(self.manager.fail_session(failed.session_id, "worker crashed"))

        replacement = self.service.ensure_session(
            "mika", {"name": "Mika"}, ensure_resources=lambda _session, _profile: None
        )

        self.assertIsNot(replacement, failed)
        self.assertEqual(replacement.cid, "mika")
        self.assertEqual(replacement.status, "created")
        self.assertIsNone(self.manager.get_session(failed.session_id))

    def test_worker_probe_handles_deleted_qt_objects(self):
        class DeletedWorker:
            def isRunning(self):
                raise RuntimeError("deleted")

        self.assertFalse(self.service.worker_is_running(DeletedWorker()))
        self.assertFalse(self.service.worker_is_running(None))


if __name__ == "__main__":
    unittest.main()
