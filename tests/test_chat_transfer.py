"""Regression coverage for global message-ID collision detection in transfer preview."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kira.chat.persistence import ChatPersistence, SqliteChatRepository
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


class _MemoryFilePort:
    def __init__(self):
        self.files = {}

    def read_bytes(self, source):
        return self.files[Path(source)]

    def write_bytes_atomically(self, directory, filename, content):
        path = Path(directory) / filename
        self.files[path] = bytes(content)
        return path


class ChatTransferPreviewTests(unittest.TestCase):
    def test_round_trip_preserves_trashed_status_lifecycle_and_organization_metadata(self):
        with tempfile.TemporaryDirectory(prefix="kira-transfer-lifecycle-") as directory:
            root = Path(directory)
            source = ChatPersistence(SqliteChatRepository(root / "source.sqlite3"))
            target = ChatPersistence(SqliteChatRepository(root / "target.sqlite3"))
            self.assertEqual(source.init_db(), [])
            self.assertEqual(target.init_db(), [])

            conversation = source.create_conversation(
                "kira", title="Portable", metadata={
                    "organization": {"favorite": True, "tags": ["research"]},
                    "external": {"preserve": "yes"},
                },
            )
            source.add_message(
                "user", "message before trash", "kira",
                conversation_id=conversation["id"],
                metadata={"source": "test"},
            )
            source.update_conversation_lifecycle([{
                "id": conversation["id"],
                "status": "trashed",
                "previous_status": "active",
                "metadata": {
                    "organization": {"favorite": True, "tags": ["research"]},
                    "external": {"preserve": "yes"},
                    "_conversation_lifecycle": {
                        "deleted_at": "2026-11-17T00:00:00+00:00",
                    },
                },
            }])

            document = ChatTransfer(source).export_data()
            imported = ChatTransfer(target).import_data(document)

            restored = target.get_conversation(conversation["id"])
            self.assertEqual(imported.imported_conversations, 1)
            self.assertEqual(restored["status"], "trashed")
            self.assertEqual(restored["metadata"]["organization"], {
                "favorite": True, "tags": ["research"]
            })
            self.assertEqual(restored["metadata"]["external"], {"preserve": "yes"})
            self.assertEqual(
                restored["metadata"]["_conversation_lifecycle"]["deleted_at"],
                "2026-11-17T00:00:00+00:00",
            )
            messages = target.get_messages(
                character_id="kira", conversation_id=conversation["id"]
            )
            self.assertEqual([item["content"] for item in messages], ["message before trash"])
            self.assertEqual(messages[0]["metadata"], {"source": "test"})

    def test_file_adapter_port_handles_import_reads_and_atomic_export_writes(self):
        file_port = _MemoryFilePort()
        transfer = ChatTransfer(_Repository(), file_port=file_port)

        destination = transfer.write_export(
            Path("memory-exports"), filename="snapshot.json"
        )

        self.assertEqual(destination, Path("memory-exports") / "snapshot.json")
        preview = transfer.preview_import(destination)
        self.assertTrue(preview.valid, preview.errors)
        self.assertEqual(preview.conversation_count, 1)

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

        document["conversations"][0]["status"] = "trashed"
        trashed_preview = transfer.preview_import(document)
        self.assertTrue(trashed_preview.valid, trashed_preview.errors)


if __name__ == "__main__":
    unittest.main()
