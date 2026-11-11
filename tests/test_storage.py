import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kira import storage


class UserDataStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_windows_default_and_explicit_data_directory(self):
        with mock.patch.dict(os.environ, {"KIRA_DATA_DIR": "", "LOCALAPPDATA": str(self.root / "Local")}, clear=False):
            self.assertEqual(storage.default_data_dir(self.root), self.root / "Local" / "Kira")
        with mock.patch.dict(os.environ, {"KIRA_DATA_DIR": str(self.root / "override")}, clear=False):
            self.assertEqual(storage.default_data_dir(self.root), self.root / "override")

    def test_legacy_migration_copies_persona_and_evidence_memory_without_overwriting(self):
        old, new = self.root / "old", self.root / "new"
        old.mkdir()
        new.mkdir()
        (old / storage.PERSONA_MEMORY_NAME).write_text('{"facts":[{"text":"remembered"}]}', encoding="utf-8")
        con = sqlite3.connect(old / storage.EVIDENCE_DB_NAME)
        con.execute("CREATE TABLE evidence_test (value TEXT)")
        con.execute("INSERT INTO evidence_test VALUES ('source-backed')")
        con.commit()
        con.close()
        (new / storage.SETTINGS_NAME).write_text('{"kept":true}', encoding="utf-8")

        note = storage.migrate_legacy(new, [old])

        self.assertIn(storage.PERSONA_MEMORY_NAME, note)
        self.assertTrue((new / storage.PERSONA_MEMORY_NAME).is_file())
        self.assertEqual((new / storage.SETTINGS_NAME).read_text(encoding="utf-8"), '{"kept":true}')
        self.assertEqual(sqlite3.connect(new / storage.EVIDENCE_DB_NAME).execute(
            "SELECT value FROM evidence_test").fetchone(), ("source-backed",))
        self.assertTrue((old / storage.PERSONA_MEMORY_NAME).is_file())
        self.assertTrue((old / storage.EVIDENCE_DB_NAME).is_file())

    def test_rolling_backup_includes_persona_and_evidence_memory(self):
        data = self.root / "data"
        data.mkdir()
        (data / storage.SETTINGS_NAME).write_text('{"api":"encrypted"}', encoding="utf-8")
        (data / storage.PERSONA_MEMORY_NAME).write_text('{"voice":["sample"]}', encoding="utf-8")
        con = sqlite3.connect(data / storage.EVIDENCE_DB_NAME)
        con.execute("CREATE TABLE evidence_test (value TEXT)")
        con.execute("INSERT INTO evidence_test VALUES ('saved')")
        con.commit()
        con.close()

        backup = storage.backup_user_data(data, min_age_hours=0)

        self.assertIsNotNone(backup)
        self.assertEqual((backup / storage.PERSONA_MEMORY_NAME).read_text(encoding="utf-8"), '{"voice":["sample"]}')
        self.assertEqual(sqlite3.connect(backup / storage.EVIDENCE_DB_NAME).execute(
            "SELECT value FROM evidence_test").fetchone(), ("saved",))


if __name__ == "__main__":
    unittest.main()
