"""Tests for the history boundary extracted from ChatApplicationService."""
from __future__ import annotations

import unittest

from kira.chat.history_facade import ChatHistoryFacade


class _Persistence:
    def __init__(self):
        self.last_error = "disk warning"

    def init_db(self):
        return ["note"]

    def get_or_create_conversation(self, character_id):
        return {"id": f"{character_id}-conversation"}

    def recent_messages(self, *args):
        return ["message"]

    def get_messages(self, *args):
        return ["full message"]

    def recent_message_records(self, *args):
        return [{"id": 1}]

    def conversation_context(self, *args):
        return [{"role": "user", "content": "hello"}]

    def message_count(self, *args):
        return 3

    def clear_memory(self, character_id):
        return character_id

    def restore_last_cleared(self):
        return 2

    def import_messages(self, source):
        return 4


class _Lifecycle:
    def get_conversation(self, conversation_id):
        return {"id": conversation_id, "character_id": "ren"}

    def archive(self, conversation_id):
        return ("archived", conversation_id)

    def list_conversations(self, **kwargs):
        return kwargs


class ChatHistoryFacadeTests(unittest.TestCase):
    def setUp(self):
        self.persistence = _Persistence()
        self.lifecycle = _Lifecycle()
        self.facade = ChatHistoryFacade(self.persistence, self.lifecycle)

    def test_history_operations_keep_character_scope_and_delegate(self):
        self.assertEqual(self.facade.init_history(), ["note"])
        self.assertEqual(self.facade.get_or_create_conversation("mika"), {"id": "mika-conversation"})
        self.assertEqual(
            self.facade.get_conversation("conversation-1"),
            {"id": "conversation-1", "character_id": "ren"},
        )
        self.assertEqual(self.facade.recent_messages(8, "ren", "conversation-1"), ["message"])
        self.assertEqual(
            self.facade.get_messages(3, "ren", "conversation-1"),
            ["full message"],
        )
        self.assertEqual(self.facade.message_count("ren", "conversation-1"), 3)
        self.assertEqual(self.facade.last_persistence_error, "disk warning")
        self.assertEqual(self.facade.archive_conversation("conversation-1"), ("archived", "conversation-1"))
        self.assertEqual(
            self.facade.list_conversations("ren", statuses=("active",)),
            {"character_id": "ren", "statuses": ("active",)},
        )

    def test_empty_character_id_and_missing_lifecycle_fail_explicitly(self):
        with self.assertRaises(ValueError):
            self.facade.get_or_create_conversation("")
        without_lifecycle = ChatHistoryFacade(self.persistence)
        with self.assertRaisesRegex(RuntimeError, "Conversation Lifecycle"):
            without_lifecycle.archive_conversation("conversation-1")


if __name__ == "__main__":
    unittest.main()
