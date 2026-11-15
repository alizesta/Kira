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

    def test_memory_only_files_are_recognized_as_user_data(self):
        folder = self.root / "legacy"
        folder.mkdir()
        (folder / "kira_persona_memory_ren.json").write_text("{}", encoding="utf-8")
        self.assertTrue(storage.has_user_data(folder))
        (folder / "kira_persona_memory_ren.json").unlink()
        con = sqlite3.connect(folder / storage.EVIDENCE_DB_NAME)
        con.execute("CREATE TABLE facts (id INTEGER)")
        con.commit()
        con.close()
        self.assertTrue(storage.has_user_data(folder))

    def test_windows_default_and_explicit_data_directory(self):
        with mock.patch.dict(os.environ, {"KIRA_DATA_DIR": "", "LOCALAPPDATA": str(self.root / "Local")}, clear=False):
            self.assertEqual(storage.default_data_dir(self.root), self.root / "Local" / "Kira")
        with mock.patch.dict(os.environ, {"KIRA_DATA_DIR": str(self.root / "override")}, clear=False):
            self.assertEqual(storage.default_data_dir(self.root), self.root / "override")

    def test_unwritable_override_falls_back_and_reconfigures_all_caches(self):
        requested = self.root / "read-only"
        fallback = self.root / "Local" / "Kira"
        requested.mkdir()
        real_check = storage._writable_directory

        def check(path):
            return False if Path(path) == requested else real_check(path)

        with mock.patch.dict(os.environ, {
            "KIRA_DATA_DIR": str(requested),
            "LOCALAPPDATA": str(self.root / "Local"),
        }, clear=False), mock.patch.object(storage, "_writable_directory", side_effect=check):
            resolved = storage.default_data_dir(self.root)
            self.assertEqual(resolved, fallback)
            self.assertEqual(os.environ["KIRA_DATA_DIR"], str(fallback))
            self.assertEqual(os.environ["HF_HOME"], str(fallback / "huggingface"))
            self.assertEqual(os.environ["TORCH_HOME"], str(fallback / "cache" / "torch"))
            self.assertIn("قابل نوشتن نبود", storage.DATA_DIR_WARNING or "")

    def test_cache_environment_uses_the_selected_data_directory(self):
        data = self.root / "Kira Attachments"
        storage.configure_cache_environment(data)
        self.assertEqual(os.environ["HF_HOME"], str(data / "huggingface"))
        self.assertEqual(os.environ["HF_HUB_CACHE"], str(data / "huggingface" / "hub"))
        self.assertEqual(os.environ["XDG_CACHE_HOME"], str(data / "cache"))
        self.assertEqual(os.environ["PIP_CACHE_DIR"], str(data / "cache" / "pip"))

    def test_legacy_migration_copies_persona_and_evidence_memory_without_overwriting(self):
        old, new = self.root / "old", self.root / "new"
        old.mkdir()
        new.mkdir()
        (old / storage.PERSONA_MEMORY_NAME).write_text('{"facts":[{"text":"remembered"}]}', encoding="utf-8")
        (old / "kira_persona_memory_ren.json").write_text('{"facts":[{"text":"Ren fact"}]}', encoding="utf-8")
        (old / "kira_persona_memory_mika.json").write_text('{"facts":[{"text":"Mika fact"}]}', encoding="utf-8")
        (new / "kira_persona_memory_ren.json").write_text('{"facts":[{"text":"destination wins"}]}', encoding="utf-8")
        con = sqlite3.connect(old / storage.EVIDENCE_DB_NAME)
        con.execute("CREATE TABLE evidence_test (value TEXT)")
        con.execute("INSERT INTO evidence_test VALUES ('source-backed')")
        con.commit()
        con.close()
        (new / storage.SETTINGS_NAME).write_text('{"kept":true}', encoding="utf-8")

        note = storage.migrate_legacy(new, [old])

        self.assertIn(storage.PERSONA_MEMORY_NAME, note)
        self.assertTrue((new / storage.PERSONA_MEMORY_NAME).is_file())
        self.assertTrue((new / "kira_persona_memory_mika.json").is_file())
        self.assertEqual((new / "kira_persona_memory_ren.json").read_text(encoding="utf-8"),
                         '{"facts":[{"text":"destination wins"}]}')
        self.assertEqual((new / storage.SETTINGS_NAME).read_text(encoding="utf-8"), '{"kept":true}')
        con = sqlite3.connect(new / storage.EVIDENCE_DB_NAME)
        try:
            self.assertEqual(con.execute("SELECT value FROM evidence_test").fetchone(), ("source-backed",))
        finally:
            con.close()
        self.assertTrue((old / storage.PERSONA_MEMORY_NAME).is_file())
        self.assertTrue((old / storage.EVIDENCE_DB_NAME).is_file())

    def test_rolling_backup_includes_persona_and_evidence_memory(self):
        data = self.root / "data"
        data.mkdir()
        (data / storage.SETTINGS_NAME).write_text('{"api":"encrypted"}', encoding="utf-8")
        (data / storage.PERSONA_MEMORY_NAME).write_text('{"voice":["sample"]}', encoding="utf-8")
        (data / "kira_persona_memory_ren.json").write_text('{"voice":["ren sample"]}', encoding="utf-8")
        (data / "kira_persona_memory_mika.json").write_text('{"voice":["mika sample"]}', encoding="utf-8")
        con = sqlite3.connect(data / storage.EVIDENCE_DB_NAME)
        con.execute("CREATE TABLE evidence_test (value TEXT)")
        con.execute("INSERT INTO evidence_test VALUES ('saved')")
        con.commit()
        con.close()

        backup = storage.backup_user_data(data, min_age_hours=0)

        self.assertIsNotNone(backup)
        self.assertEqual((backup / storage.PERSONA_MEMORY_NAME).read_text(encoding="utf-8"), '{"voice":["sample"]}')
        self.assertEqual((backup / "kira_persona_memory_ren.json").read_text(encoding="utf-8"), '{"voice":["ren sample"]}')
        self.assertEqual((backup / "kira_persona_memory_mika.json").read_text(encoding="utf-8"), '{"voice":["mika sample"]}')
        con = sqlite3.connect(backup / storage.EVIDENCE_DB_NAME)
        try:
            self.assertEqual(con.execute("SELECT value FROM evidence_test").fetchone(), ("saved",))
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
