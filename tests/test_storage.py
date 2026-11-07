import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from tests import helpers  # noqa: F401
from kira import storage


def make_data(folder, text="settings-v1", rows=("a", "b")):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / storage.SETTINGS_NAME).write_text(text, encoding="utf-8")
    con = sqlite3.connect(folder / storage.DB_NAME)
    con.execute("CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, role TEXT, content TEXT)")
    for r in rows:
        con.execute("INSERT INTO messages(role, content) VALUES('user', ?)", (r,))
    con.commit()
    con.close()


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kira_storage_"))

    def test_default_dir_is_localappdata_outside_program_folder(self):
        old = {k: os.environ.get(k) for k in ("KIRA_DATA_DIR", "LOCALAPPDATA")}
        try:
            os.environ.pop("KIRA_DATA_DIR", None)
            os.environ["LOCALAPPDATA"] = str(self.tmp / "Local")
            root = self.tmp / "Project_Kira"
            self.assertEqual(storage.default_data_dir(root), self.tmp / "Local" / "Kira")
            os.environ["KIRA_DATA_DIR"] = str(self.tmp / "override")
            self.assertEqual(storage.default_data_dir(root), self.tmp / "override")
            os.environ.pop("KIRA_DATA_DIR")
            os.environ.pop("LOCALAPPDATA")
            self.assertEqual(storage.default_data_dir(root), root / "data")
        finally:
            for k, v in old.items():
                os.environ.pop(k, None)
                if v is not None:
                    os.environ[k] = v

    def test_migration_copies_and_never_touches_old_folder(self):
        old = self.tmp / "Project_Kira_v1_4_5" / "data"
        make_data(old, "OLD-SETTINGS")
        new = self.tmp / "Local" / "Kira"
        note = storage.migrate_legacy(new, [old])
        self.assertIn("کپی شد", note)
        self.assertEqual((new / storage.SETTINGS_NAME).read_text(encoding="utf-8"), "OLD-SETTINGS")
        self.assertTrue((old / storage.SETTINGS_NAME).exists() and (old / storage.DB_NAME).exists())   # old data untouched
        rows = sqlite3.connect(new / storage.DB_NAME).execute("SELECT content FROM messages").fetchall()
        self.assertEqual(rows, [("a",), ("b",)])

    def test_migration_never_overwrites_existing_new_data(self):
        old = self.tmp / "Project_Kira_old" / "data"
        make_data(old, "OLD")
        new = self.tmp / "Local" / "Kira"
        make_data(new, "NEW-ALREADY-HERE")
        self.assertIsNone(storage.migrate_legacy(new, [old]))
        self.assertEqual((new / storage.SETTINGS_NAME).read_text(encoding="utf-8"), "NEW-ALREADY-HERE")

    def test_migration_runs_once_even_if_user_later_deletes_files(self):
        old = self.tmp / "Project_Kira_old" / "data"
        make_data(old)
        new = self.tmp / "Local" / "Kira"
        storage.migrate_legacy(new, [old])
        (new / storage.SETTINGS_NAME).unlink()
        (new / storage.DB_NAME).unlink()
        self.assertIsNone(storage.migrate_legacy(new, [old]))                 # marker: do not resurrect old data

    def test_sibling_kira_folders_are_found_newest_first(self):
        root = self.tmp / "Project_Kira_v1_4_7"
        (root).mkdir()
        old_a, old_b = self.tmp / "Project_Kira_v1_4_5" / "data", self.tmp / "Project_Kira_v1_4_6" / "data"
        make_data(old_a, "A")
        make_data(old_b, "B")
        past = time.time() - 5000
        for f in old_a.iterdir():
            os.utime(f, (past, past))
        make_data(self.tmp / "Other_Program" / "data", "X")
        found = storage.legacy_candidates(root)
        self.assertEqual(found[0], old_b)
        self.assertEqual(found, [old_b, old_a])

    def test_backup_rolls_and_is_consistent(self):
        data = self.tmp / "Kira"
        make_data(data)
        first = storage.backup_user_data(data, keep=3, min_age_hours=12)
        self.assertTrue((first / storage.SETTINGS_NAME).exists())
        self.assertEqual(sqlite3.connect(first / storage.DB_NAME).execute("SELECT COUNT(*) FROM messages").fetchone()[0], 2)
        self.assertIsNone(storage.backup_user_data(data, keep=3, min_age_hours=12))     # too soon: skipped
        for i in range(5):                                                              # force several more
            time.sleep(1.05)
            storage.backup_user_data(data, keep=3, min_age_hours=0)
        self.assertEqual(len(list((data / "backups").iterdir())), 3)

    def test_backup_with_nothing_to_back_up(self):
        self.assertIsNone(storage.backup_user_data(self.tmp / "empty", keep=3))


if __name__ == "__main__":
    unittest.main()
