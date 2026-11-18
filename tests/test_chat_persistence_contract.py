"""Isolated contract and repository tests for Qt-free chat persistence."""
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from kira.chat.persistence import ChatPersistence, ChatRepository, PersistenceError, SqliteChatRepository, create_default_chat_persistence


class FakeRepository:
    def __init__(self):
        self.last_error = None
        self.messages = []
        self.fail_clear = False

    def init_db(self):
        return []

    def add_message(self, role, content, character_id=None, **options):
        self.messages.append({"role": role, "content": content, "character_id": character_id})
        return True

    def conversation_context(self, limit=12, max_chars=12000, character_id=None, conversation_id=None):
        return self.recent_messages(limit, character_id, conversation_id)

    def recent_messages(self, limit=12, character_id=None, conversation_id=None):
        rows = [m for m in self.messages if character_id is None or m["character_id"] == character_id]
        return [{"role": m["role"], "content": m["content"]} for m in rows[-limit:]]

    def message_count(self, character_id=None, conversation_id=None):
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

    def test_injected_contract_is_independent_of_qt_and_main_window(self):
        self.assertIs(self.persistence._repository, self.repository)
        self.assertNotIn("PySide6", str(ChatPersistence.__module__))

    def test_character_scoping_prevents_history_leak_between_personas(self):
        self.persistence.add_message("user", "Kira", "kira")
        self.persistence.add_message("user", "Ren", "ren")
        self.persistence.add_message("assistant", "Mika", "mika")
        self.assertEqual(self.persistence.message_count("ren"), 1)
        self.assertEqual(self.persistence.recent_messages(10, "ren"), [{"role": "user", "content": "Ren"}])
        self.assertEqual(self.persistence.message_count(), 3)

    def test_repository_owns_order_and_context_retrieval(self):
        self.persistence.add_message("user", "first", "kira")
        self.persistence.add_message("assistant", "second", "kira")
        self.assertEqual(self.persistence.recent_messages(10, "kira"), [
            {"role": "user", "content": "first"}, {"role": "assistant", "content": "second"}
        ])
        self.assertEqual(self.persistence.conversation_context(10, character_id="kira")[-1]["content"], "second")

    def test_repository_failure_is_normalized_at_boundary(self):
        self.repository.fail_clear = True
        with self.assertRaisesRegex(PersistenceError, "snapshot unavailable"):
            self.persistence.clear_memory("kira")

    def test_flush_pending_is_optional_for_repositories_without_a_write_queue(self):
        self.assertEqual(self.persistence.flush_pending(), 0)

    def test_error_state_is_owned_by_repository(self):
        self.persistence.set_last_error("disk unavailable")
        self.assertEqual(self.persistence.last_error, "disk unavailable")


class SqliteChatRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="kira-persistence-")
        self.db = Path(self.temp.name) / "kira_memory.sqlite3"
        self.repository = SqliteChatRepository(self.db)
        self.persistence = ChatPersistence(self.repository)
        self.assertEqual(self.persistence.init_db(), [])

    def tearDown(self):
        self.temp.cleanup()

    def test_fresh_database_is_created_without_a_fake_pre_migration_backup(self):
        self.assertEqual(self.persistence.list_snapshots("pre-migration"), [])
        self.persistence.add_message("user", "first message", "kira")
        self.assertEqual(self.persistence.list_snapshots("pre-migration"), [])

    def test_factory_creates_real_replaceable_sqlite_repository(self):
        persistence = create_default_chat_persistence(Path(self.temp.name) / "factory.sqlite3")
        self.assertIsInstance(persistence._repository, SqliteChatRepository)
        self.assertIsInstance(persistence._repository, ChatRepository)
        self.assertEqual(persistence.init_db(), [])

    def test_conversation_id_is_stable_for_character_across_reopen(self):
        first = self.persistence.get_or_create_conversation("ren")
        reopened = SqliteChatRepository(self.db)
        second = reopened.get_or_create_conversation("ren")
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["character_id"], "ren")

    def test_new_conversations_for_same_character_are_independent(self):
        first = self.persistence.create_conversation("ren", title="first")
        second = self.persistence.create_conversation("ren", title="second")
        self.persistence.add_message("user", "one", "ren", conversation_id=first["id"])
        self.persistence.add_message("user", "two", "ren", conversation_id=second["id"])
        self.assertEqual(self.persistence.recent_messages(10, "ren", first["id"]), [{"role": "user", "content": "one"}])
        self.assertEqual(self.persistence.recent_messages(10, "ren", second["id"]), [{"role": "user", "content": "two"}])

    def test_atomic_conversation_metadata_mutations_rollback_as_a_batch(self):
        first = self.persistence.create_conversation(
            "kira", title="first", metadata={"external": {"keep": True}}
        )
        second = self.persistence.create_conversation(
            "kira", title="second", metadata={"external": {"keep": True}}
        )

        def mutate(record):
            metadata = dict(record["metadata"])
            metadata["organization"] = {"favorite": True}
            if record["id"] == second["id"]:
                raise RuntimeError("simulated second-row failure")
            record["metadata"] = metadata
            return record

        with self.assertRaisesRegex(PersistenceError, "simulated second-row failure"):
            self.persistence.mutate_conversations([
                (first["id"], mutate),
                (second["id"], mutate),
            ])

        self.assertEqual(
            self.persistence.get_conversation(first["id"])["metadata"],
            {"external": {"keep": True}},
        )
        self.assertEqual(
            self.persistence.get_conversation(second["id"])["metadata"],
            {"external": {"keep": True}},
        )

    def test_atomic_mutate_all_is_character_scoped_and_preserves_other_metadata(self):
        kira = self.persistence.create_conversation(
            "kira", title="Kira", metadata={"external": {"keep": 1}}
        )
        ren = self.persistence.create_conversation(
            "ren", title="Ren", metadata={"external": {"keep": 2}}
        )

        def mutate(record):
            metadata = dict(record["metadata"])
            organization = dict(metadata.get("organization", {}))
            organization["tags"] = ["reviewed"]
            metadata["organization"] = organization
            record["metadata"] = metadata
            return record

        updated = self.persistence.mutate_all_conversations("kira", mutate)

        self.assertEqual(set(updated), {kira["id"]})
        self.assertEqual(
            self.persistence.get_conversation(kira["id"])["metadata"],
            {"external": {"keep": 1}, "organization": {"tags": ["reviewed"]}},
        )
        self.assertEqual(
            self.persistence.get_conversation(ren["id"])["metadata"],
            {"external": {"keep": 2}},
        )

    def test_mutate_conversation_persists_nested_in_place_metadata_changes(self):
        conversation = self.persistence.create_conversation(
            "kira", metadata={"external": {"settings": {"labels": ["before"]}}}
        )

        def mutate(record):
            record["metadata"]["external"]["settings"]["labels"].append("after")
            return record

        updated = self.persistence.mutate_conversations([
            (conversation["id"], mutate),
        ])

        self.assertEqual(
            updated[conversation["id"]]["metadata"]["external"]["settings"]["labels"],
            ["before", "after"],
        )
        self.assertEqual(
            self.persistence.get_conversation(conversation["id"])["metadata"],
            {"external": {"settings": {"labels": ["before", "after"]}}},
        )

    def test_mutate_all_persists_nested_in_place_metadata_changes(self):
        first = self.persistence.create_conversation(
            "kira", metadata={"external": {"flags": {"seen": False}}}
        )
        second = self.persistence.create_conversation(
            "kira", metadata={"external": {"flags": {"seen": False}}}
        )

        def mutate(record):
            record["metadata"]["external"]["flags"]["seen"] = True
            return record

        updated = self.persistence.mutate_all_conversations("kira", mutate)

        self.assertEqual(set(updated), {first["id"], second["id"]})
        for conversation_id in (first["id"], second["id"]):
            self.assertTrue(
                self.persistence.get_conversation(conversation_id)["metadata"]["external"]["flags"]["seen"]
            )

    def test_metadata_mutation_cannot_change_lifecycle_or_character_fields(self):
        conversation = self.persistence.create_conversation("kira", title="protected")

        def mutate(record):
            record["status"] = "archived"
            return record

        with self.assertRaisesRegex(PersistenceError, "cannot change status"):
            self.persistence.mutate_conversations([(conversation["id"], mutate)])

        current = self.persistence.get_conversation(conversation["id"])
        self.assertEqual(current["status"], "active")
        self.assertEqual(current["title"], "protected")

    def test_metadata_mutation_rejects_non_finite_json_numbers(self):
        conversation = self.persistence.create_conversation("kira")

        def mutate(record):
            record["metadata"]["invalid"] = float("nan")
            return record

        with self.assertRaisesRegex(PersistenceError, "not JSON serializable"):
            self.persistence.mutate_all_conversations("kira", mutate)

        self.assertEqual(
            self.persistence.get_conversation(conversation["id"])["metadata"],
            {},
        )

    def test_mutate_all_rolls_back_every_row_when_a_later_callback_fails(self):
        first = self.persistence.create_conversation(
            "kira", metadata={"external": {"keep": "first"}}
        )
        second = self.persistence.create_conversation(
            "kira", metadata={"external": {"keep": "second"}}
        )

        def mutate(record):
            record["metadata"]["organization"] = {"favorite": True}
            if record["id"] == second["id"]:
                raise RuntimeError("simulated bulk callback failure")
            return record

        with self.assertRaisesRegex(PersistenceError, "simulated bulk callback failure"):
            self.persistence.mutate_all_conversations("kira", mutate)

        self.assertEqual(
            self.persistence.get_conversation(first["id"])["metadata"],
            {"external": {"keep": "first"}},
        )
        self.assertEqual(
            self.persistence.get_conversation(second["id"])["metadata"],
            {"external": {"keep": "second"}},
        )

    def test_metadata_timestamp_order_and_partial_status_round_trip(self):
        conversation = self.persistence.get_or_create_conversation("mika")
        self.persistence.add_message(
            "assistant", "partial output", "mika", conversation_id=conversation["id"],
            metadata={"provider": "test", "attempt": 2}, status="interrupted",
        )
        row = self.persistence.get_messages(character_id="mika", conversation_id=conversation["id"])[0]
        self.assertEqual(row["metadata"], {"provider": "test", "attempt": 2})
        self.assertEqual(row["status"], "interrupted")
        self.assertTrue(row["created_at"])

    def test_stream_updates_are_idempotent_under_one_message_id(self):
        conversation = self.persistence.get_or_create_conversation("kira")
        self.persistence.update_stream_message(9001, "part 1", character_id="kira", conversation_id=conversation["id"])
        self.persistence.update_stream_message(9001, "part 1 + part 2", character_id="kira",
                                               conversation_id=conversation["id"], status="interrupted")
        rows = self.persistence.get_messages(character_id="kira", conversation_id=conversation["id"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["content"], "part 1 + part 2")
        self.assertEqual(rows[0]["status"], "interrupted")

    def test_import_restores_conversation_metadata_and_is_idempotent(self):
        source_path = Path(self.temp.name) / "import-source.sqlite3"
        source = SqliteChatRepository(source_path)
        source.init_db()
        conversation = source.create_conversation(
            "mika", title="Imported conversation", metadata={"origin": "archive", "pinned": True}
        )
        source.add_message("user", "archived message", "mika", conversation_id=conversation["id"])
        source_message_id = source.message_id_for("user", "archived message", "mika")

        self.assertEqual(self.persistence.import_messages(source_path), 1)
        restored = self.persistence.get_conversation(conversation["id"])
        self.assertEqual(restored["title"], "Imported conversation")
        self.assertEqual(restored["metadata"], {"origin": "archive", "pinned": True})
        self.assertEqual(
            self.persistence.recent_messages(10, "mika", conversation["id"]),
            [{"role": "user", "content": "archived message"}],
        )
        imported = self.persistence.get_messages(character_id="mika", conversation_id=conversation["id"])
        self.assertEqual(imported[0]["id"], source_message_id)
        self.assertEqual(self.persistence.import_messages(source_path), 0)

    def test_import_reassigns_only_colliding_ids_without_rewriting_existing_messages(self):
        self.persistence.add_message("user", "target row", "kira")
        existing = self.persistence.get_messages(character_id="kira")[0]
        source_path = Path(self.temp.name) / "id-collision.sqlite3"
        source = SqliteChatRepository(source_path)
        source.init_db()
        conversation = source.create_conversation("ren", title="source")
        source.add_message("user", "source row", "ren", conversation_id=conversation["id"])
        source_id = source.message_id_for("user", "source row", "ren")
        self.assertEqual(source_id, existing["id"])

        self.assertEqual(self.persistence.import_messages(source_path), 1)
        after = self.persistence.get_messages(character_id="kira")
        self.assertEqual([(row["id"], row["content"]) for row in after], [(existing["id"], "target row")])
        imported = self.persistence.get_messages(character_id="ren", conversation_id=conversation["id"])
        self.assertEqual(len(imported), 1)
        self.assertNotEqual(imported[0]["id"], source_id)
        self.assertGreater(imported[0]["id"], existing["id"])

    def test_stream_message_id_cannot_be_reused_by_another_character(self):
        kira = self.persistence.get_or_create_conversation("kira")
        ren = self.persistence.get_or_create_conversation("ren")
        self.persistence.update_stream_message(
            9200, "Kira partial", character_id="kira", conversation_id=kira["id"]
        )
        with self.assertRaisesRegex(PersistenceError, "متعلق به"):
            self.persistence.update_stream_message(
                9200, "Ren overwrite", character_id="ren", conversation_id=ren["id"]
            )
        rows = self.persistence.get_messages(character_id="kira", conversation_id=kira["id"])
        self.assertEqual([row["content"] for row in rows], ["Kira partial"])
        self.assertEqual(self.persistence.message_count("ren"), 0)

    def test_deleting_conversation_does_not_touch_another_persona(self):
        ren = self.persistence.get_or_create_conversation("ren")
        mika = self.persistence.get_or_create_conversation("mika")
        self.persistence.add_message("user", "ren", "ren", conversation_id=ren["id"])
        self.persistence.add_message("user", "mika", "mika", conversation_id=mika["id"])
        self.assertEqual(self.persistence.delete_conversation(ren["id"]), 1)
        self.assertEqual(self.persistence.message_count("ren"), 0)
        self.assertEqual(self.persistence.recent_messages(10, "mika"), [{"role": "user", "content": "mika"}])

    def test_database_outage_keeps_pending_write_on_the_existing_active_conversation(self):
        from unittest import mock

        conversation = self.persistence.get_or_create_conversation("ren")
        with mock.patch.object(self.repository, "_db", side_effect=sqlite3.OperationalError("database is locked")):
            self.assertFalse(self.persistence.add_message("user", "pending", "ren"))
        self.assertEqual(self.repository.pending_count(), 1)
        self.assertEqual(self.repository._pending[0][3], conversation["id"])

        self.assertTrue(self.persistence.add_message("assistant", "after recovery", "ren"))
        rows = self.persistence.get_messages(character_id="ren", conversation_id=conversation["id"])
        self.assertEqual([row["content"] for row in rows], ["pending", "after recovery"])

    def test_concurrent_saves_across_characters_are_not_lost(self):
        failures = []
        def worker(character):
            for i in range(30):
                try:
                    if not self.persistence.add_message("user", f"{character}-{i}", character):
                        failures.append((character, i))
                except Exception as exc:
                    failures.append((character, i, repr(exc)))
        threads = [threading.Thread(target=worker, args=(cid,)) for cid in ("kira", "ren", "mika")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(failures, [])
        self.assertEqual(self.persistence.message_count(), 90)
        self.assertEqual(self.persistence.message_count("ren"), 30)

    def test_lifecycle_batch_updates_multiple_conversations_without_touching_messages(self):
        first = self.persistence.create_conversation("kira", title="first")
        second = self.persistence.create_conversation("ren", title="second")
        self.persistence.add_message("user", "first message", "kira", conversation_id=first["id"])
        self.persistence.add_message("user", "second message", "ren", conversation_id=second["id"])

        self.assertTrue(self.persistence.update_conversation_lifecycle([
            {
                "id": first["id"], "status": "archived", "previous_status": "active",
                "metadata": {"organization": {"favorite": True}, "audit": "kept"},
            },
            {
                "id": second["id"], "status": "trashed", "previous_status": "active",
                "metadata": {"_conversation_lifecycle": {"deleted_at": "2026-11-17T00:00:00+00:00"}},
            },
        ]))

        self.assertEqual(self.persistence.get_conversation(first["id"])["status"], "archived")
        self.assertEqual(self.persistence.get_conversation(first["id"])["metadata"]["audit"], "kept")
        self.assertEqual(self.persistence.get_conversation(second["id"])["status"], "trashed")
        self.assertEqual(self.persistence.message_count("kira", first["id"]), 1)
        self.assertEqual(self.persistence.message_count("ren", second["id"]), 1)

    def test_lifecycle_batch_rolls_back_every_target_on_stale_expected_state(self):
        first = self.persistence.create_conversation("kira", title="first")
        second = self.persistence.create_conversation("ren", title="second")

        with self.assertRaisesRegex(PersistenceError, "state changed concurrently"):
            self.persistence.update_conversation_lifecycle([
                {
                    "id": first["id"], "status": "archived", "previous_status": "active",
                    "metadata": {"marker": "must roll back"},
                },
                {
                    "id": second["id"], "status": "trashed", "previous_status": "archived",
                    "metadata": {},
                },
            ])

        self.assertEqual(self.persistence.get_conversation(first["id"])["status"], "active")
        self.assertEqual(self.persistence.get_conversation(first["id"])["metadata"], {})
        self.assertEqual(self.persistence.get_conversation(second["id"])["status"], "active")

    def test_permanent_delete_refuses_declared_foreign_key_dependents(self):
        conversation = self.persistence.create_conversation("kira", title="protected")
        with self.repository._db() as con:
            con.execute(
                "CREATE TABLE conversation_references ("
                "id INTEGER PRIMARY KEY, conversation_id TEXT NOT NULL "
                "REFERENCES conversations(id))"
            )
            con.execute(
                "INSERT INTO conversation_references(conversation_id) VALUES (?)",
                (conversation["id"],),
            )
        self.persistence.update_conversation_lifecycle([{
            "id": conversation["id"], "status": "trashed", "previous_status": "active",
            "metadata": {"_conversation_lifecycle": {"deleted_at": "2026-11-17T00:00:00+00:00"}},
        }])

        with self.assertRaisesRegex(PersistenceError, "dependent records"):
            self.persistence.delete_conversation(conversation["id"], expected_status="trashed")

        self.assertIsNotNone(self.persistence.get_conversation(conversation["id"]))

    def test_permanent_delete_rechecks_expected_state_and_removes_only_target(self):
        first = self.persistence.create_conversation("kira", title="first")
        second = self.persistence.create_conversation("ren", title="second")
        self.persistence.add_message("user", "first message", "kira", conversation_id=first["id"])
        self.persistence.add_message("user", "second message", "ren", conversation_id=second["id"])
        self.persistence.update_conversation_lifecycle([{
            "id": first["id"], "status": "trashed", "previous_status": "active",
            "metadata": {"_conversation_lifecycle": {"deleted_at": "2026-11-17T00:00:00+00:00"}},
        }])

        with self.assertRaisesRegex(PersistenceError, "state changed"):
            self.persistence.delete_conversation(first["id"], expected_status="active")

        self.assertEqual(self.persistence.delete_conversation(first["id"], expected_status="trashed"), 1)
        self.assertIsNone(self.persistence.get_conversation(first["id"]))
        self.assertEqual(self.persistence.recent_messages(10, "ren", second["id"]), [
            {"role": "user", "content": "second message"}
        ])

    def test_migration_rollback_keeps_legacy_schema_and_backup_for_retry(self):
        self.db.unlink()
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT)")
        con.execute("INSERT INTO messages(role, content, created_at) VALUES ('user', 'keep me', '2025-01-01 10:00:00')")
        con.commit()
        con.close()

        original_create = self.repository._create_schema

        def fail_after_schema_writes(connection):
            original_create(connection)
            raise sqlite3.OperationalError("simulated migration interruption")

        from unittest import mock
        with mock.patch.object(self.repository, "_create_schema", side_effect=fail_after_schema_writes):
            notes = self.persistence.init_db()
        self.assertTrue(notes)
        self.assertTrue(self.repository.list_snapshots("pre-migration"))

        con = sqlite3.connect(self.db)
        columns = {row[1] for row in con.execute("PRAGMA table_info(messages)")}
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        original = con.execute("SELECT role, content FROM messages").fetchall()
        con.close()
        self.assertNotIn("conversation_id", columns)
        self.assertNotIn("conversations", tables)
        self.assertEqual(original, [("user", "keep me")])

        self.assertEqual(self.persistence.init_db(), [])
        self.assertEqual([row["content"] for row in self.persistence.get_messages(100, "kira")], ["keep me"])

    def test_newer_persistence_schema_record_is_refused_before_schema_changes(self):
        self.db.unlink()
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, role TEXT, content TEXT, created_at TEXT)")
        con.execute("CREATE TABLE persistence_schema (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT NOT NULL)")
        con.execute("INSERT INTO persistence_schema(version, applied_at, description) VALUES (2, '2026-01-01', 'future')")
        con.commit()
        con.close()

        notes = self.persistence.init_db()
        self.assertTrue(notes)
        self.assertIn("جدیدتر", notes[0])
        con = sqlite3.connect(self.db)
        columns = {row[1] for row in con.execute("PRAGMA table_info(messages)")}
        con.close()
        self.assertNotIn("conversation_id", columns)

    def test_newer_schema_version_is_refused_without_downgrade(self):
        self.db.unlink()
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, role TEXT, content TEXT, created_at TEXT)")
        con.execute("INSERT INTO messages VALUES (1, 'user', 'newer data', '2026-01-01 00:00:00')")
        con.execute("PRAGMA user_version = 2")
        con.commit()
        con.close()

        notes = self.persistence.init_db()
        self.assertTrue(notes)
        self.assertIn("جدیدتر", notes[0])
        con = sqlite3.connect(self.db)
        version = con.execute("PRAGMA user_version").fetchone()[0]
        columns = {row[1] for row in con.execute("PRAGMA table_info(messages)")}
        rows = con.execute("SELECT content FROM messages").fetchall()
        con.close()
        self.assertEqual(version, 2)
        self.assertNotIn("conversation_id", columns)
        self.assertEqual(rows, [("newer data",)])

    def test_legacy_schema_migrates_additively_and_preserves_messages(self):
        self.db.unlink()
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT NOT NULL, content TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        con.executemany("INSERT INTO messages(role, content, created_at) VALUES (?, ?, ?)", [
            ("user", "legacy user", "2025-01-01 10:00:00"),
            ("assistant", "legacy answer", "2025-01-01 10:00:01"),
        ])
        con.commit()
        con.close()

        notes = self.persistence.init_db()
        self.assertEqual(notes, [])
        rows = self.persistence.get_messages(character_id="kira")
        self.assertEqual([row["content"] for row in rows], ["legacy user", "legacy answer"])
        self.assertTrue(rows[0]["conversation_id"])
        self.assertEqual(rows[0]["metadata"], {})
        self.assertEqual(rows[0]["status"], "complete")
        self.assertTrue(self.repository.list_snapshots("pre-migration"))

        con = sqlite3.connect(self.db)
        columns = {row[1] for row in con.execute("PRAGMA table_info(messages)")}
        version = con.execute("PRAGMA user_version").fetchone()[0]
        con.close()
        self.assertTrue({"conversation_id", "metadata", "status", "character_id"} <= columns)
        self.assertEqual(version, 1)


if __name__ == "__main__":
    unittest.main()
