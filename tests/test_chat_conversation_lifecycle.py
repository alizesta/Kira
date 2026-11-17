from datetime import datetime, timezone

import pytest

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


def test_archive_and_restore_preserve_identity_and_unrelated_metadata():
    repository, events = _Repository(), _Events()
    service = _service(repository, events)

    archived = service.archive("conv-a")
    assert archived.previous_status == "active"
    assert archived.new_status == "archived"
    assert archived.event_published is True
    assert repository.rows["conv-a"]["id"] == "conv-a"
    assert repository.rows["conv-a"]["metadata"]["custom"] == "preserved"
    assert repository.rows["conv-a"]["metadata"]["_conversation_lifecycle"]["archived_at"].startswith("2026-11-17")

    restored = service.restore("conv-a")
    assert restored.new_status == "active"
    assert repository.rows["conv-a"]["id"] == "conv-a"
    assert len(events.published) == 2


def test_group_archive_is_one_atomic_batch_and_hides_archived_from_default_list():
    repository = _Repository()
    service = _service(repository)

    results = service.archive_many(["conv-a", "conv-b"])

    assert len(results) == 2
    assert len(repository.batch_calls) == 1
    assert service.list_conversations() == []
    assert {row["id"] for row in service.list_conversations(statuses=(ConversationStatus.ARCHIVED,))} == {
        "conv-a", "conv-b"
    }


def test_group_archive_rejects_missing_target_before_writing_anything():
    repository = _Repository()
    service = _service(repository)

    with pytest.raises(ConversationNotFound):
        service.archive_many(["conv-a", "missing"])

    assert repository.batch_calls == []
    assert repository.rows["conv-a"]["status"] == "active"


def test_soft_delete_restore_and_permanent_delete_authorization():
    repository = _Repository()
    service = _service(repository)

    trashed = service.trash("conv-a")
    assert trashed.new_status == "trashed"
    assert repository.rows["conv-a"]["metadata"]["_conversation_lifecycle"]["deleted_at"]

    restored = service.restore_trashed("conv-a")
    assert restored.new_status == "active"
    service.trash("conv-a")

    with pytest.raises(PermanentDeleteAuthorizationError):
        service.permanent_delete("conv-a", authorization=_Authorization(False))
    assert "conv-a" in repository.rows

    authorization = _Authorization(True)
    deleted = service.permanent_delete("conv-a", authorization=authorization)
    assert deleted.new_status == "deleted"
    assert authorization.checked_ids == ["conv-a"]
    assert repository.deleted == [("conv-a", "trashed")]
    assert "conv-a" not in repository.rows


def test_permanent_delete_requires_trashed_state():
    service = _service()

    with pytest.raises(InvalidConversationTransition):
        service.permanent_delete("conv-a", authorization=_Authorization(True))
