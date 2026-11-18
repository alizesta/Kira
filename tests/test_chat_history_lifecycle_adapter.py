"""Integration coverage for lifecycle operations through the application adapter."""
import tempfile
import unittest
from pathlib import Path

from kira.chat.conversation_lifecycle import ConversationLifecycleService
from kira.chat.persistence import SqliteChatRepository
from kira.services.chat_history_service import SqliteChatHistoryService


class _Events:
    def publish(self, event_type, *, payload=None, metadata=None, **kwargs):
        return type("Dispatch", (), {"duplicate": False})()


class _Authorization:
    def authorize_permanent_delete(self, conversation_id):
        return conversation_id == "target"


class ChatHistoryLifecycleAdapterTests(unittest.TestCase):
    def test_lifecycle_service_uses_application_adapter_for_atomic_updates_and_delete(self):
        with tempfile.TemporaryDirectory(prefix="kira-lifecycle-adapter-") as directory:
            repository = SqliteChatRepository(Path(directory) / "chat.sqlite3")
            history = SqliteChatHistoryService(repository)
            self.assertEqual(history.init_db(), [])

            conversation = history.create_conversation(
                "kira", title="Lifecycle adapter", conversation_id="target"
            )
            lifecycle = ConversationLifecycleService(history, _Events())

            archived = lifecycle.archive(conversation["id"])
            self.assertEqual(archived.new_status, "archived")
            self.assertEqual(history.get_conversation("target")["status"], "archived")

            trashed = lifecycle.trash("target")
            self.assertEqual(trashed.new_status, "trashed")
            deleted = lifecycle.permanent_delete(
                "target", authorization=_Authorization()
            )

            self.assertEqual(deleted.new_status, "deleted")
            self.assertIsNone(history.get_conversation("target"))


if __name__ == "__main__":
    unittest.main()
