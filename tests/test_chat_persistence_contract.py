"""Isolated contract tests for the Qt-free chat persistence boundary."""
import unittest
from pathlib import Path

from kira.chat.persistence import (
    ChatPersistence,
    LegacyMemoryRepository,
    PersistenceError,
    create_default_chat_persistence,
)


class FakeRepository:
    def __init__(self):
        self.last_error = None
        self.messages = []
        self.fail_clear = False

    def init_db(self):
        return []

    def add_message(self, role, content, character_id=None):
        self.messages.append({"role": role, "content": content, "character_id": character_id})
        return True

    def conversation_context(self, limit=12, max_chars=12000, character_id=None):
        rows = self.recent_messages(limit, character_id)
        return rows

    def recent_messages(self, limit=12, character_id=None):
        rows = [m for m in self.messages if character_id is None or m["character_id"] == character_id]
        return [{"role": m["role"], "content": m["content"]} for m in rows[-limit:]]

    def message_count(self, character_id=None):
        return len([m for m in self.messages if character_id is None or m["character_id"] == character_id])

    def clear_memory(self, character_id=None):
        if self.fail_clear:
            raise OSError("snapshot unavailable")
        if character_id is None:
            self.messages.clear()
        else:
            self.messages[:] = [m for m in self.messages if m["character_id"] != character_id]

    def restore_last_cleared(self):
        return 0

    def import_messages(self, source):
        return 0


class ChatPersistenceContractTests(unittest.TestCase):
    def setUp(self):
        self.repository = FakeRepository()
        self.persistence = ChatPersistence(self.repository)

    def test_persistence_is_injected_and_does_not_require_qt_or_main_window(self):
        self.assertIs(self.persistence._repository, self.repository)
        self.assertNotIn("PySide6", str(ChatPersistence.__module__))

    def test_messages_are_scoped_by_character_without_cross_session_leak(self):
        self.persistence.add_message("user", "Kira", "kira")
        self.persistence.add_message("user", "Ren", "ren")
        self.persistence.add_message("assistant", "Mika", "mika")
        self.assertEqual(self.persistence.message_count("ren"), 1)
        self.assertEqual(self.persistence.recent_messages(10, "ren"), [
            {"role": "user", "content": "Ren"}
        ])
        self.assertEqual(self.persistence.message_count(), 3)

    def test_repository_owns_order_and_context_retrieval(self):
        self.persistence.add_message("user", "first", "kira")
        self.persistence.add_message("assistant", "second", "kira")
        self.assertEqual(self.persistence.recent_messages(10, "kira"), [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "second"},
        ])
        self.assertEqual(self.persistence.conversation_context(10, character_id="kira")[-1]["content"], "second")

    def test_clear_is_scoped_and_repository_failure_is_normalized(self):
        self.persistence.add_message("user", "keep", "kira")
        self.persistence.add_message("user", "remove", "ren")
        self.persistence.clear_memory("ren")
        self.assertEqual(self.persistence.message_count(), 1)
        self.repository.fail_clear = True
        with self.assertRaisesRegex(PersistenceError, "snapshot unavailable"):
            self.persistence.clear_memory("kira")

    def test_error_state_is_owned_by_repository(self):
        self.persistence.set_last_error("disk unavailable")
        self.assertEqual(self.persistence.last_error, "disk unavailable")

    def test_default_factory_uses_replaceable_legacy_repository(self):
        store = FakeRepository()
        persistence = create_default_chat_persistence(store)
        self.assertIsInstance(persistence, ChatPersistence)
        self.assertIsInstance(persistence._repository, LegacyMemoryRepository)
        persistence.add_message("user", "saved", "kira")
        self.assertEqual(store.message_count("kira"), 1)


if __name__ == "__main__":
    unittest.main()
