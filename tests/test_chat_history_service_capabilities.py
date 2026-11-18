"""Regression tests for extended SqliteChatHistoryService capability delegation."""
from __future__ import annotations

import unittest

from kira.chat.persistence import ChatPersistence
from kira.services.chat_history_service import SqliteChatHistoryService


class RecordingRepository:
    def __init__(self):
        self.calls = []

    def mutate_conversations(self, mutations):
        self.calls.append(("mutate_conversations", mutations))
        return {"conversation-1": {"id": "conversation-1"}}

    def mutate_all_conversations(self, character_id, mutator):
        self.calls.append(("mutate_all_conversations", character_id, mutator))
        return {}

    def messages_after(self, after_id, limit):
        self.calls.append(("messages_after", after_id, limit))
        return [{"id": after_id + 1}]

    def get_transfer_messages(
        self, conversation_id, character_id, after_created_at, after_id, limit
    ):
        self.calls.append((
            "get_transfer_messages", conversation_id, character_id,
            after_created_at, after_id, limit,
        ))
        return [{"id": 7, "conversation_id": conversation_id}]

    def import_transfer_records(self, conversations, messages):
        self.calls.append(("import_transfer_records", conversations, messages))
        return {"imported_conversations": len(conversations), "imported_messages": len(messages)}


class ChatHistoryServiceCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.repository = RecordingRepository()
        self.service = SqliteChatHistoryService(ChatPersistence(self.repository))

    def test_organization_mutations_delegate_to_atomic_persistence(self):
        mutations = [("conversation-1", lambda row: row)]
        self.assertIn("conversation-1", self.service.mutate_conversations(mutations))
        self.assertEqual(self.service.mutate_all_conversations("kira", lambda row: row), {})
        self.assertEqual(self.repository.calls[0][0], "mutate_conversations")
        self.assertEqual(self.repository.calls[1][0], "mutate_all_conversations")

    def test_search_and_transfer_reads_preserve_paging_parameters(self):
        self.assertEqual(self.service.messages_after(5, 17), [{"id": 6}])
        self.assertEqual(
            self.service.get_transfer_messages(
                "conversation-1", "ren", "2026-11-18", 12, 25
            ),
            [{"id": 7, "conversation_id": "conversation-1"}],
        )
        self.assertEqual(self.repository.calls[0], ("messages_after", 5, 17))
        self.assertEqual(
            self.repository.calls[1],
            ("get_transfer_messages", "conversation-1", "ren", "2026-11-18", 12, 25),
        )

    def test_transfer_import_delegates_to_single_persistence_transaction(self):
        conversations = [{"id": "conversation-1"}]
        messages = [{"id": 7}]
        result = self.service.import_transfer_records(conversations, messages)
        self.assertEqual(result, {"imported_conversations": 1, "imported_messages": 1})
        self.assertEqual(
            self.repository.calls,
            [("import_transfer_records", conversations, messages)],
        )


if __name__ == "__main__":
    unittest.main()
