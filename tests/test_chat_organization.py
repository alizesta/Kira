import copy
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from kira.chat.organization import (
    ChatOrganizationService,
    OrganizationError,
    OrganizationFilter,
    OrganizationRepositoryError,
)


class _Repository:
    def __init__(self):
        self.rows = {
            "kira-1": {
                "id": "kira-1", "character_id": "kira", "title": "Alpha",
                "created_at": "2026-01-01", "updated_at": "2026-01-03",
                "metadata": {"external": {"keep": True}},
            },
            "kira-2": {
                "id": "kira-2", "character_id": "kira", "title": "Beta",
                "created_at": "2026-01-02", "updated_at": "2026-01-04",
                "metadata": {},
            },
            "ren-1": {
                "id": "ren-1", "character_id": "ren", "title": "Ren note",
                "created_at": "2026-01-03", "updated_at": "2026-01-02",
                "metadata": {},
            },
        }
        self.fail_update = False
        self.fail_mutation_after = None
        self._lock = threading.RLock()
        self.read_during_mutation = []

    def get_conversation(self, conversation_id):
        row = self.rows.get(conversation_id)
        return copy.deepcopy(row) if row is not None else None

    def list_conversations(self, character_id=None):
        is_owned = getattr(self._lock, "_is_owned", lambda: False)
        self.read_during_mutation.append(bool(is_owned()))
        records = list(self.rows.values())
        if character_id is not None:
            records = [row for row in records if row["character_id"] == character_id]
        return copy.deepcopy(records)

    def mutate_conversations(self, mutations):
        with self._lock:
            snapshot = copy.deepcopy(self.rows)
            result = {}
            try:
                for index, (conversation_id, mutator) in enumerate(mutations, start=1):
                    if self.fail_update or self.fail_mutation_after == index:
                        raise OSError("storage unavailable")
                    row = self.rows.get(conversation_id)
                    if row is None:
                        raise OSError(f"conversation not found: {conversation_id}")
                    updated = mutator(copy.deepcopy(row))
                    self.rows[conversation_id] = copy.deepcopy(updated)
                    result[conversation_id] = copy.deepcopy(updated)
                return result
            except Exception:
                self.rows = snapshot
                raise

    def mutate_all_conversations(self, character_id, mutator):
        with self._lock:
            snapshot = copy.deepcopy(self.rows)
            result = {}
            selected = [
                key for key, row in self.rows.items()
                if character_id is None or row["character_id"] == character_id
            ]
            try:
                for index, conversation_id in enumerate(selected, start=1):
                    if self.fail_update or self.fail_mutation_after == index:
                        raise OSError("storage unavailable")
                    updated = mutator(copy.deepcopy(self.rows[conversation_id]))
                    self.rows[conversation_id] = copy.deepcopy(updated)
                    result[conversation_id] = copy.deepcopy(updated)
                return result
            except Exception:
                self.rows = snapshot
                raise


class _Events:
    def __init__(self):
        self.events = []

    def publish(self, event_type, *, payload=None, **kwargs):
        self.events.append((str(event_type), copy.deepcopy(payload or {})))


class ChatOrganizationServiceTests(unittest.TestCase):
    def setUp(self):
        self.repository = _Repository()
        self.events = _Events()
        self.service = ChatOrganizationService(
            self.repository, character_id="kira", event_publisher=self.events
        )

    def test_rename_preserves_manual_titles_against_automatic_suggestions(self):
        manual = self.service.rename_conversation("kira-1", "My title")
        self.assertEqual(manual.value, "My title")
        automatic = self.service.rename_conversation("kira-1", "Suggested title", automatic=True)
        self.assertEqual(automatic.value, "manual-title-preserved")
        self.assertEqual(self.repository.rows["kira-1"]["title"], "My title")
        self.assertEqual(self.repository.rows["kira-1"]["metadata"]["external"], {"keep": True})

    def test_tags_are_case_insensitive_and_delete_tag_clears_all_assignments(self):
        self.service.add_tag("kira-1", "Important")
        self.service.add_tag("kira-1", "important")
        self.service.add_tag("kira-2", "IMPORTANT")
        self.assertEqual(self.service.get_organization("kira-1").metadata["tags"], ["Important"])
        changed = self.service.delete_tag("important")
        self.assertEqual(changed, 2)
        self.assertEqual(self.service.get_organization("kira-1").metadata["tags"], [])
        self.assertEqual(self.service.get_organization("kira-2").metadata["tags"], [])

    def test_folder_assignment_is_discoverable_and_delete_resets_to_inbox(self):
        folder = self.service.create_folder("Projects")
        self.service.move_conversation("kira-1", folder.id)

        # Folder assignment is durable in the conversation metadata; a new
        # service instance can resolve the assigned folder without a second store.
        restarted = ChatOrganizationService(self.repository, character_id="kira")
        restarted.move_conversation("kira-2", folder.id)
        self.assertEqual(restarted.get_organization("kira-2").metadata["folder_id"], "projects")
        self.assertTrue(
            self.repository.read_during_mutation[-1],
            "folder existence must be checked while the repository write lock is held",
        )

        changed = restarted.delete_folder(folder.id)
        self.assertEqual(changed, 2)
        self.assertEqual(restarted.get_organization("kira-1").metadata["folder_id"], "inbox")
        self.assertEqual(restarted.get_organization("kira-2").metadata["folder_id"], "inbox")

    def test_character_scope_prevents_cross_character_access(self):
        with self.assertRaises(OrganizationError):
            self.service.get_organization("ren-1")
        with self.assertRaises(OrganizationError):
            self.service.move_conversation("ren-1", "inbox")

    def test_favorite_metadata_filters_combine_with_and_semantics(self):
        self.service.add_tag("kira-1", "work")
        self.service.add_tag("kira-2", "work")
        self.service.set_favorite("kira-1", True)
        self.service.update_metadata("kira-1", {"category": "Research", "description": "Useful notes"})
        self.service.update_metadata("kira-2", {"category": "research"})

        result = self.service.filter_conversations(OrganizationFilter(
            tags=("WORK",), favorite=True, category="research", query="useful",
            sort_by="title", descending=False,
        ))
        self.assertEqual([row["id"] for row in result], ["kira-1"])
        self.assertEqual(result[0]["organization"]["category"], "Research")

    def test_update_metadata_preserves_unknown_keys_and_rejects_reserved_fields(self):
        self.service.update_metadata("kira-1", {"description": "details", "color": "violet", "order": "4"})
        metadata = self.repository.rows["kira-1"]["metadata"]
        self.assertEqual(metadata["external"], {"keep": True})
        self.assertEqual(metadata["organization"]["description"], "details")
        self.assertEqual(metadata["organization"]["order"], 4)
        with self.assertRaises(OrganizationError):
            self.service.update_metadata("kira-1", {"favorite": True})

    def test_labels_reject_control_characters_and_invalid_lengths(self):
        with self.assertRaises(OrganizationError):
            self.service.create_folder("one\ntwo")
        with self.assertRaises(OrganizationError):
            self.service.rename_conversation("kira-1", "x" * 121)

    def test_non_finite_numbers_are_rejected_in_organization_metadata(self):
        with self.assertRaises(OrganizationError):
            self.service.update_metadata("kira-1", {"score": float("nan")})

    def test_optional_description_can_be_cleared(self):
        self.service.update_metadata("kira-1", {"description": "temporary"})
        self.service.update_metadata("kira-1", {"description": ""})
        organization = self.service.get_organization("kira-1").metadata
        self.assertNotIn("description", organization)

    def test_competing_sqlite_writers_do_not_lose_organization_updates(self):
        with tempfile.TemporaryDirectory(prefix="kira-organization-race-") as directory:
            database = Path(directory) / "history.sqlite3"
            from kira.chat.persistence import ChatPersistence, SqliteChatRepository

            first_persistence = ChatPersistence(SqliteChatRepository(database))
            second_persistence = ChatPersistence(SqliteChatRepository(database))
            self.assertEqual(first_persistence.init_db(), [])
            conversation = first_persistence.create_conversation("kira", title="Concurrent")
            services = [
                ChatOrganizationService(ChatPersistence(SqliteChatRepository(database)), character_id="kira")
                for _ in range(4)
            ]
            barrier = threading.Barrier(len(services))
            labels = ("alpha", "beta", "gamma", "delta")

            def add_competing_tag(item):
                service, label = item
                barrier.wait(timeout=10)
                return service.add_tag(conversation["id"], label)

            with ThreadPoolExecutor(max_workers=len(services)) as pool:
                results = list(pool.map(
                    add_competing_tag,
                    zip(services, labels),
                ))

            self.assertTrue(all(result.success for result in results))
            stored = first_persistence.get_conversation(conversation["id"])
            self.assertEqual(
                set(stored["metadata"]["organization"]["tags"]),
                {"alpha", "beta", "gamma", "delta"},
            )

    def test_bulk_delete_is_atomic_when_one_conversation_update_fails(self):
        self.service.add_tag("kira-1", "obsolete")
        self.service.add_tag("kira-2", "obsolete")
        self.repository.fail_mutation_after = 2

        with self.assertRaises(OrganizationRepositoryError):
            self.service.delete_tag("obsolete")

        self.assertEqual(
            self.service.get_organization("kira-1").metadata["tags"], ["obsolete"]
        )
        self.assertEqual(
            self.service.get_organization("kira-2").metadata["tags"], ["obsolete"]
        )

    def test_sqlite_bulk_delete_rolls_back_when_a_later_row_update_fails(self):
        with tempfile.TemporaryDirectory(prefix="kira-organization-atomic-") as directory:
            database = Path(directory) / "history.sqlite3"
            from kira.chat.persistence import ChatPersistence, SqliteChatRepository

            persistence = ChatPersistence(SqliteChatRepository(database))
            self.assertEqual(persistence.init_db(), [])
            first = persistence.create_conversation("kira", title="first")
            second = persistence.create_conversation("kira", title="second")
            service = ChatOrganizationService(persistence, character_id="kira")
            service.add_tag(first["id"], "obsolete")
            service.add_tag(second["id"], "obsolete")

            # Force the second UPDATE to fail after the first UPDATE has run.
            # The repository must roll both writes back as one SQLite transaction.
            escaped_id = second["id"].replace("'", "''")
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "CREATE TRIGGER reject_second_organization_update "
                    "BEFORE UPDATE OF metadata ON conversations "
                    f"WHEN OLD.id = '{escaped_id}' "
                    "BEGIN SELECT RAISE(ABORT, 'simulated disk constraint'); END"
                )

            with self.assertRaises(OrganizationRepositoryError):
                service.delete_tag("obsolete")

            self.assertEqual(
                persistence.get_conversation(first["id"])["metadata"]["organization"]["tags"],
                ["obsolete"],
            )
            self.assertEqual(
                persistence.get_conversation(second["id"])["metadata"]["organization"]["tags"],
                ["obsolete"],
            )

    def test_repository_failures_are_normalized(self):
        self.repository.fail_update = True
        with self.assertRaises(OrganizationRepositoryError):
            self.service.set_favorite("kira-1", True)

    def test_metadata_change_events_are_best_effort(self):
        self.service.set_favorite("kira-1", True)
        self.assertTrue(self.events.events)
        event_type, payload = self.events.events[-1]
        self.assertEqual(event_type, "conversation_metadata_updated")
        self.assertEqual(payload["conversation_id"], "kira-1")


if __name__ == "__main__":
    unittest.main()
