from datetime import datetime, timezone
import unittest

from kira.chat.conversation_lifecycle import (
    ConversationLifecycleService,
    ConversationNotFound,
    ConversationStatus,
    InvalidConversationTransition,
    PermanentDeleteAuthorizationError,
)


class _Repository:
    def __init__(self):
        self.rows = {
            "conv-a": {
                "id": "conv-a", "character_id": "kira", "status": "active",
                "metadata": {"custom": "preserved"},
            },
            "conv-b": {
                "id": "conv-b", "character_id": "ren", "status": "active",
                "metadata": {},
            },
        }
        self.batch_calls = []
        self.deleted = []

    def get_conversation(self, conversation_id):
        row = self.rows.get(conversation_id)
        return dict(row) if row is not None else None

    def list_conversations(self, character_id=None):
        rows = list(self.rows.values())
        if character_id is not None:
            rows = [row for row in rows if row["character_id"] == character_id]
        return [dict(row) for row in rows]

    def update_conversation_lifecycle(self, changes):
        self.batch_calls.append(changes)
        for item in changes:
            row = self.rows.get(item["id"])
            if row is None or row["status"] != item["previous_status"]:
                raise RuntimeError("stale batch")
        for item in changes:
            self.rows[item["id"]].update(
                status=item["status"], metadata=dict(item["metadata"])
            )
        return True

    def delete_conversation(self, conversation_id, *, expected_status=None):
        row = self.rows.get(conversation_id)
        if row is None or row["status"] != expected_status:
            raise RuntimeError("unexpected delete state")
        self.deleted.append((conversation_id, expected_status))
        del self.rows[conversation_id]
        return 0


class _Events:
    def __init__(self):
        self.published = []

    def publish(self, event_type, *, payload=None, metadata=None, **kwargs):
        self.published.append((event_type, dict(payload or {})))
        return type("Dispatch", (), {"duplicate": False})()


class _Authorization:
    def __init__(self, allowed):
        self.allowed = allowed
        self.checked_ids = []

    def authorize_permanent_delete(self, conversation_id):
        self.checked_ids.append(conversation_id)
        return self.allowed


def _service(repository=None, events=None):
    return ConversationLifecycleService(
        repository or _Repository(),
        events or _Events(),
        clock=lambda: datetime(2026, 11, 17, tzinfo=timezone.utc),
    )


class ChatConversationLifecycleTests(unittest.TestCase):
    def test_archive_and_restore_preserve_identity_and_unrelated_metadata(self):
        repository, events = _Repository(), _Events()
        service = _service(repository, events)

        archived = service.archive("conv-a")
        self.assertEqual(archived.previous_status, "active")
        self.assertEqual(archived.new_status, "archived")
        self.assertTrue(archived.event_published)
        self.assertEqual(repository.rows["conv-a"]["id"], "conv-a")
        self.assertEqual(repository.rows["conv-a"]["metadata"]["custom"], "preserved")
        self.assertTrue(
            repository.rows["conv-a"]["metadata"]["_conversation_lifecycle"]["archived_at"].startswith("2026-11-17")
        )

        restored = service.restore("conv-a")
        self.assertEqual(restored.new_status, "active")
        self.assertEqual(repository.rows["conv-a"]["id"], "conv-a")
        self.assertEqual(len(events.published), 2)

    def test_group_archive_is_one_atomic_batch_and_hides_archived_from_default_list(self):
        repository = _Repository()
        service = _service(repository)

        results = service.archive_many(["conv-a", "conv-b"])

        self.assertEqual(len(results), 2)
        self.assertEqual(len(repository.batch_calls), 1)
        self.assertEqual(service.list_conversations(), [])
        self.assertEqual(
            {row["id"] for row in service.list_conversations(statuses=(ConversationStatus.ARCHIVED,))},
            {"conv-a", "conv-b"},
        )

    def test_group_archive_rejects_missing_target_before_writing_anything(self):
        repository = _Repository()
        service = _service(repository)

        with self.assertRaises(ConversationNotFound):
            service.archive_many(["conv-a", "missing"])

        self.assertEqual(repository.batch_calls, [])
        self.assertEqual(repository.rows["conv-a"]["status"], "active")

    def test_soft_delete_restore_and_permanent_delete_authorization(self):
        repository = _Repository()
        service = _service(repository)

        trashed = service.trash("conv-a")
        self.assertEqual(trashed.new_status, "trashed")
        self.assertTrue(repository.rows["conv-a"]["metadata"]["_conversation_lifecycle"]["deleted_at"])

        restored = service.restore_trashed("conv-a")
        self.assertEqual(restored.new_status, "active")
        service.trash("conv-a")

        with self.assertRaises(PermanentDeleteAuthorizationError):
            service.permanent_delete("conv-a", authorization=_Authorization(False))
        self.assertIn("conv-a", repository.rows)

        authorization = _Authorization(True)
        deleted = service.permanent_delete("conv-a", authorization=authorization)
        self.assertEqual(deleted.new_status, "deleted")
        self.assertEqual(authorization.checked_ids, ["conv-a"])
        self.assertEqual(repository.deleted, [("conv-a", "trashed")])
        self.assertNotIn("conv-a", repository.rows)

    def test_permanent_delete_requires_trashed_state(self):
        service = _service()
        with self.assertRaises(InvalidConversationTransition):
            service.permanent_delete("conv-a", authorization=_Authorization(True))


if __name__ == "__main__":
    unittest.main()
