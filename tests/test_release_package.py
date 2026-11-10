"""Portable tests for the release archive's naming and data-exclusion rules."""
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.build_release import release_stamp, should_skip


class ReleasePackageTests(unittest.TestCase):
    def test_timestamp_uses_project_zip_format(self):
        now = datetime(2026, 11, 11, 3, 7, tzinfo=ZoneInfo("Asia/Tehran"))
        self.assertEqual(release_stamp(now), "261111_0307")

    def test_runtime_and_user_data_are_excluded(self):
        for name in (
            ".venv/Lib/site-packages/package.py",
            "kira/__pycache__/main.cpython-312.pyc",
            "logs/kira.log",
            "data/kira_memory.sqlite3",
            "settings.json",
            "ProjectKira_261111_0059.zip",
        ):
            with self.subTest(name=name):
                self.assertTrue(should_skip(Path(name)))

    def test_example_environment_file_is_kept(self):
        self.assertFalse(should_skip(Path(".env.example")))


if __name__ == "__main__":
    unittest.main()
