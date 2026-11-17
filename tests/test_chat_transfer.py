"""Regression coverage for global message-ID collision detection in transfer preview."""
from __future__ import annotations

import unittest

from kira.chat.transfer import ChatTransfer


class _Repository:
    def list_conversations(self, character_id=None):
        return [{"id": "unrelated-conversation", "character_id": "ren"}]

    def messages_after(self, after_id=0, limit=500):
        if after_id < 41:
            return [{"id": 41}]
        return []

    def get_transfer_messages(
        self, conversation_id, character_id, after_created_at="", after_id=0, limit=1000
    ):
        return []

    def import_transfer_records(self, conversations, messages):
        raise AssertionError("preview must not mutate persistence")


class ChatTransferPreviewTests(unittest.TestCase):
    def test_preview_reports_message_id_collision_from_another_conversation(self):
        transfer = ChatTransfer(_Repository())
        document = {
            "schema_version": 1,
            "export_version": "1.0",
            "exported_at": "2026-11-17T00:00:00Z",
            "conversations": [{
                "id": "new-conversation",
                "character_id": "kira",
                "title": "Imported",
                "metadata": {},
                "status": "active",
                "created_at": "2026-11-16T00:00:00Z",
                "updated_at": "2026-11-16T00:00:00Z",
                "messages": [{
                    "id": 41,
                    "role": "user",
                    "content": "hello",
                    "created_at": "2026-11-16T00:00:01Z",
                    "character_id": "kira",
                    "conversation_id": "new-conversation",
                    "metadata": {},
                    "status": "complete",
                }],
            }],
        }

        preview = transfer.preview_import(document)

        self.assertTrue(preview.valid, preview.errors)
        self.assertTrue(
            any("message ID collisions" in warning for warning in preview.warnings),
            preview.warnings,
        )


if __name__ == "__main__":
    unittest.main()
