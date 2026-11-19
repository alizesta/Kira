"""Focused tests for application-owned proactive Initiative orchestration."""
import unittest
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace

from kira.app.initiative_application import InitiativeApplicationService


class _Memory:
    def __init__(self, items):
        self.items = items
        self.calls = []

    def list_items(self, character_id, now=None):
        self.calls.append((character_id, now))
        return list(self.items)


class _Mood:
    def __init__(self):
        self.marked = []

    @contextmanager
    def character_scope(self, character_id, traits=None):
        yield self

    def current(self, now=None):
        return {
            "age": 7200,
            "last_initiative": 0,
            "last_initiative_memory_id": "",
            "recent_events": [],
        }

    def mark_initiative_sent(self, memory_id=None, now=None):
        self.marked.append((memory_id, now))


class _Chat:
    def __init__(self, persisted=True):
        self.persisted = persisted
        self.messages = []

    def recent_message_records(self, *, limit, character_id):
        return []

    def persist_message(self, *args, **kwargs):
        self.messages.append((args, kwargs))
        return SimpleNamespace(ok=self.persisted)


class InitiativeApplicationServiceTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0).timestamp()
        self.memory = _Memory([{
            "id": "memory-1",
            "group": "moment",
            "kind": "event",
            "text": 'he said "I have an exam"',
            "ts": self.now - 60,
        }])
        self.mood = _Mood()
        self.chat = _Chat()
        self.service = InitiativeApplicationService(self.memory, self.mood, self.chat)
        self.session = SimpleNamespace(
            cid="ren",
            session_id="session-ren",
            application_request_id="request-1",
            conversation_id="conversation-ren",
            busy=False,
            draft="",
        )
        self.profiles = {"ren": {"name": "Ren"}}
        self.traits = {"ren": {"warmth": 1}}
        self.settings = {}

    def test_persists_checkin_and_marks_mood_only_after_success(self):
        result = self.service.run_checkin(
            self.session, self.profiles, self.traits, self.settings,
            (self.session,), now=self.now,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.character_id, "ren")
        self.assertTrue(result.message)
        self.assertEqual(len(self.chat.messages), 1)
        self.assertEqual(self.memory.calls, [("ren", self.now)])
        self.assertEqual(self.chat.messages[0][1]["metadata"]["proactive"], "initiative")
        self.assertEqual(self.chat.messages[0][1]["metadata"]["memory_id"], "memory-1")
        self.assertEqual(self.mood.marked, [("memory-1", self.now)])
        self.assertEqual(result.history[-1]["memory_id"], "memory-1")

    def test_failed_persistence_does_not_mark_mood_or_return_history(self):
        self.chat.persisted = False
        result = self.service.run_checkin(
            self.session, self.profiles, self.traits, self.settings,
            (self.session,), now=self.now,
        )
        self.assertIsNone(result)
        self.assertEqual(self.mood.marked, [])

    def test_merge_settings_history_preserves_other_characters_and_recovers_corrupt_value(self):
        from kira.app.initiative_application import InitiativeCheckIn

        result = InitiativeCheckIn(
            character_id="ren",
            message="check-in",
            history=({"at": self.now, "memory_id": "memory-1"},),
        )
        merged = self.service.merge_settings_history(
            {"character_initiative_history": {"kira": [{"at": self.now, "memory_id": "k"}]}},
            result,
        )
        self.assertIn("kira", merged)
        self.assertEqual(merged["ren"], [{"at": self.now, "memory_id": "memory-1"}])

        recovered = self.service.merge_settings_history(
            {"character_initiative_history": "corrupt legacy value"}, result
        )
        self.assertEqual(recovered, {"ren": [{"at": self.now, "memory_id": "memory-1"}]})

    def test_recent_activity_in_another_character_suppresses_checkin(self):
        class RecentMood(_Mood):
            def current(self, now=None):
                return {
                    "age": 90,
                    "last_initiative": 0,
                    "last_initiative_memory_id": "",
                    "recent_events": [],
                }

        service = InitiativeApplicationService(self.memory, RecentMood(), self.chat)
        result = service.run_checkin(
            self.session,
            {"ren": {"name": "Ren"}, "kira": {"name": "Kira"}},
            {"ren": {}, "kira": {}},
            {},
            (self.session,),
            now=self.now,
        )
        self.assertIsNone(result)
        self.assertEqual(self.chat.messages, [])

    def test_history_lookup_failure_suppresses_checkin_before_persisting(self):
        self.chat.recent_message_records = lambda **_kwargs: (_ for _ in ()).throw(
            RuntimeError("history unavailable")
        )
        result = self.service.run_checkin(
            self.session, self.profiles, self.traits, self.settings,
            (self.session,), now=self.now,
        )
        self.assertIsNone(result)
        self.assertEqual(self.chat.messages, [])
        self.assertEqual(self.mood.marked, [])

    def test_any_busy_or_malformed_session_suppresses_checkin(self):
        busy = SimpleNamespace(busy=True, draft="")
        result = self.service.run_checkin(
            self.session, self.profiles, self.traits, self.settings,
            (self.session, busy), now=self.now,
        )
        self.assertIsNone(result)
        self.assertEqual(self.chat.messages, [])


if __name__ == "__main__":
    unittest.main()
