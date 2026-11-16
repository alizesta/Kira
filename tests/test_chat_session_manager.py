"""Independent Qt-free tests for Chat Session lifecycle and state ownership."""
from __future__ import annotations

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from kira.chat.session_manager import SessionManager, SessionStatus
from kira.chat_sessions import ChatSession


class SessionManagerTests(unittest.TestCase):
    def make_manager(self, **overrides):
        resolved = []

        def resolve_conversation(character_id):
            resolved.append(character_id)
            return {"id": f"conversation-{character_id}", "metadata": {"persisted": True}}

        options = {"session_factory": ChatSession, "conversation_resolver": resolve_conversation}
        options.update(overrides)
        return SessionManager(**options), resolved

    def test_create_session_has_identity_timestamps_metadata_and_persistence_reference(self):
        manager, resolved = self.make_manager()
        session = manager.create_session("Kira", metadata={"source": "test"})
        self.assertEqual(session.cid, "kira")
        self.assertEqual(session.character_id, "kira")
        self.assertTrue(session.session_id)
        self.assertEqual(session.status, SessionStatus.CREATED.value)
        self.assertEqual(session.conversation_id, "conversation-kira")
        self.assertTrue(session.created_at)
        self.assertEqual(session.created_at, session.updated_at)
        self.assertEqual(session.metadata, {"persisted": True, "source": "test"})
        self.assertEqual(resolved, ["kira"])
        self.assertIs(manager.get_session(session.session_id), session)
        self.assertIs(manager.get_session_for_character("kira"), session)

    def test_create_is_idempotent_per_character_and_recreation_gets_a_new_id(self):
        manager, resolved = self.make_manager()
        first = manager.create_session("ren")
        self.assertIs(manager.create_session("REN"), first)
        self.assertEqual(resolved, ["ren"])
        self.assertTrue(manager.close_session(first.session_id))
        second = manager.create_session("ren")
        self.assertNotEqual(first.session_id, second.session_id)
        self.assertIs(manager.get_session(first.session_id), first)
        self.assertIs(manager.get_session_for_character("ren"), second)

    def test_activation_deactivation_and_active_lookup(self):
        manager, _ = self.make_manager()
        kira = manager.create_session("kira")
        ren = manager.create_session("ren")
        self.assertTrue(manager.activate_session(kira.session_id))
        self.assertIs(manager.get_active_session(), kira)
        self.assertEqual(kira.status, SessionStatus.ACTIVE.value)
        self.assertTrue(manager.activate_session(ren.session_id))
        self.assertEqual(kira.status, SessionStatus.IDLE.value)
        self.assertEqual(ren.status, SessionStatus.ACTIVE.value)
        self.assertIs(manager.get_active_session(), ren)
        self.assertTrue(manager.deactivate_session(ren.session_id))
        self.assertTrue(manager.deactivate_session(ren.session_id))
        self.assertIsNone(manager.get_active_session())
        self.assertEqual(ren.status, SessionStatus.IDLE.value)

    def test_sessions_and_character_states_are_isolated(self):
        manager, _ = self.make_manager()
        sessions = {cid: manager.create_session(cid) for cid in ("kira", "ren", "mika")}
        manager.activate_session(sessions["ren"].session_id)
        sessions["mika"].busy = True
        self.assertEqual(sessions["ren"].status, SessionStatus.ACTIVE.value)
        self.assertEqual(sessions["kira"].status, SessionStatus.CREATED.value)
        self.assertEqual(sessions["mika"].status, SessionStatus.CREATED.value)
        self.assertFalse(getattr(sessions["kira"], "busy", False))
        self.assertTrue(sessions["mika"].busy)
        self.assertEqual(set(manager.sessions_by_character), {"kira", "ren", "mika"})

    def test_close_drains_active_work_before_disposal_and_rejects_activation(self):
        pending = {"ren": True}
        disposed = []
        manager, _ = self.make_manager(
            has_pending_work=lambda session: pending[session.cid],
            dispose_callback=lambda session: disposed.append(session.session_id),
        )
        ren = manager.create_session("ren")
        mika = manager.create_session("mika")
        manager.activate_session(ren.session_id)
        self.assertFalse(manager.close_session(ren.session_id))
        self.assertEqual(ren.status, SessionStatus.CLOSING.value)
        self.assertIsNone(manager.get_active_session())
        self.assertIs(manager.get_session_for_character("ren"), ren)
        self.assertFalse(manager.activate_session(ren.session_id))
        self.assertEqual(disposed, [])
        self.assertEqual(mika.status, SessionStatus.CREATED.value)
        pending["ren"] = False
        self.assertTrue(manager.close_session(ren.session_id))
        self.assertEqual(ren.status, SessionStatus.CLOSED.value)
        self.assertEqual(disposed, [ren.session_id])
        self.assertTrue(manager.close_session(ren.session_id))
        self.assertEqual(disposed, [ren.session_id])

    def test_close_one_session_does_not_affect_other_sessions(self):
        manager, _ = self.make_manager()
        kira = manager.create_session("kira")
        ren = manager.create_session("ren")
        mika = manager.create_session("mika")
        manager.activate_session(mika.session_id)
        self.assertTrue(manager.close_session(ren.session_id))
        self.assertEqual(kira.status, SessionStatus.CREATED.value)
        self.assertEqual(mika.status, SessionStatus.ACTIVE.value)
        self.assertIs(manager.get_active_session(), mika)
        self.assertIsNone(manager.get_session_for_character("ren"))
        self.assertIn("mika", manager.sessions_by_character)

    def test_closed_session_cannot_be_reactivated(self):
        manager, _ = self.make_manager()
        session = manager.create_session("kira")
        self.assertTrue(manager.close_session(session.session_id))
        self.assertFalse(manager.activate_session(session.session_id))
        self.assertFalse(manager.reopen_session(session.session_id))
        self.assertEqual(session.status, SessionStatus.CLOSED.value)

    def test_closing_session_can_be_reopened_before_disposal_if_character_returns(self):
        manager, _ = self.make_manager(has_pending_work=lambda _session: True)
        session = manager.create_session("ren")
        self.assertFalse(manager.close_session(session.session_id))
        self.assertTrue(manager.reopen_session(session.session_id))
        self.assertEqual(session.status, SessionStatus.IDLE.value)
        self.assertTrue(manager.activate_session(session.session_id))

    def test_duplicate_deactivation_and_close_are_idempotent(self):
        manager, _ = self.make_manager()
        session = manager.create_session("kira")
        self.assertTrue(manager.deactivate_session(session.session_id))
        self.assertTrue(manager.deactivate_session(session.session_id))
        self.assertTrue(manager.close_session(session.session_id))
        self.assertTrue(manager.close_session(session.session_id))
        self.assertFalse(manager.activate_session(session.session_id))

    def test_state_events_are_ordered_and_unsubscription_works(self):
        manager, _ = self.make_manager()
        events = []
        unsubscribe = manager.subscribe(events.append)
        session = manager.create_session("ren")
        manager.activate_session(session.session_id)
        manager.deactivate_session(session.session_id)
        self.assertEqual([event.status for event in events], ["created", "active", "idle"])
        self.assertTrue(unsubscribe())
        self.assertFalse(unsubscribe())
        manager.close_session(session.session_id)
        self.assertEqual(len(events), 3)

    def test_disposal_failure_is_visible_and_can_be_retried(self):
        failures = {"count": 1}
        def dispose(_session):
            if failures["count"]:
                failures["count"] -= 1
                raise RuntimeError("resource still referenced")
        manager, _ = self.make_manager(dispose_callback=dispose)
        session = manager.create_session("mika")
        self.assertFalse(manager.close_session(session.session_id))
        self.assertEqual(session.status, SessionStatus.FAILED.value)
        self.assertIn("resource disposal failed", session.last_error)
        self.assertTrue(manager.close_session(session.session_id))
        self.assertEqual(session.status, SessionStatus.CLOSED.value)

    def test_concurrent_activation_keeps_exactly_one_session_active(self):
        manager, _ = self.make_manager()
        sessions = [manager.create_session(cid) for cid in ("kira", "ren", "mika")]
        barrier = threading.Barrier(len(sessions))
        def activate(session):
            barrier.wait()
            return manager.activate_session(session.session_id)
        with ThreadPoolExecutor(max_workers=len(sessions)) as pool:
            results = list(pool.map(activate, sessions))
        self.assertTrue(all(results))
        active = [s for s in manager.list_sessions() if s.status == SessionStatus.ACTIVE.value]
        self.assertEqual(len(active), 1)
        self.assertIs(manager.get_active_session(), active[0])

    def test_dispose_drains_every_session_and_is_idempotent(self):
        disposed = []
        pending = {"kira": True, "ren": False}
        manager, _ = self.make_manager(
            has_pending_work=lambda session: pending[session.cid],
            dispose_callback=lambda session: disposed.append(session.cid),
        )
        kira = manager.create_session("kira")
        ren = manager.create_session("ren")
        self.assertFalse(manager.dispose())
        self.assertFalse(manager.is_disposed)
        self.assertEqual(ren.status, SessionStatus.CLOSED.value)
        self.assertEqual(kira.status, SessionStatus.CLOSING.value)
        pending["kira"] = False
        self.assertTrue(manager.dispose())
        self.assertTrue(manager.is_disposed)
        self.assertTrue(manager.dispose())
        self.assertEqual(set(disposed), {"kira", "ren"})
        with self.assertRaises(RuntimeError):
            manager.create_session("mika")


if __name__ == "__main__":
    unittest.main()
