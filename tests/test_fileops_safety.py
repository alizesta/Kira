"""Security and rollback tests for legacy file move tools."""

import errno
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kira.tools.access import PathPolicy
from kira.tools.fileops import FileTools, _move_file_no_overwrite
from kira.tools.registry import ToolError


class FileMoveSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root = base / "allowed"
        self.data = base / "data"
        self.root.mkdir()
        self.data.mkdir()
        self.policy = PathPolicy({"tools_allowed_paths": [str(self.root)]}, self.data)
        self.tools = FileTools(self.policy)

    def tearDown(self):
        self.tmp.cleanup()

    def test_legacy_move_tool_rejects_directories(self):
        source = self.root / "folder"
        destination = self.root / "destination"
        source.mkdir()
        destination.mkdir()
        with self.assertRaisesRegex(ToolError, "فقط یک فایل"):
            self.tools.precheck_move({"source": str(source), "destination_folder": str(destination)})

    def test_cross_device_move_uses_staging_and_removes_source_only_after_copy(self):
        source = self.root / "source.txt"
        destination_folder = self.root / "destination"
        destination_folder.mkdir()
        target = destination_folder / source.name
        source.write_text("payload", encoding="utf-8")
        real_link = os.link
        calls = 0

        def fail_first_link(src, dst):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError(errno.EXDEV, "cross-device link")
            return real_link(src, dst)

        with mock.patch("kira.tools.fileops.os.link", side_effect=fail_first_link):
            _move_file_no_overwrite(str(source), str(target))

        self.assertFalse(source.exists())
        self.assertEqual(target.read_text(encoding="utf-8"), "payload")
        self.assertEqual(list(destination_folder.glob(".kira-move-*.tmp")), [])

    def test_failed_cross_device_copy_keeps_source_and_removes_partial_temp(self):
        source = self.root / "source.txt"
        destination_folder = self.root / "destination"
        destination_folder.mkdir()
        target = destination_folder / source.name
        source.write_text("payload", encoding="utf-8")

        with mock.patch("kira.tools.fileops.os.link", side_effect=OSError(errno.EXDEV, "cross-device")), mock.patch(
            "kira.tools.fileops.os.fsync", side_effect=OSError("simulated disk full")
        ):
            with self.assertRaises(OSError):
                _move_file_no_overwrite(str(source), str(target))

        self.assertTrue(source.exists())
        self.assertFalse(target.exists())
        self.assertEqual(list(destination_folder.glob(".kira-move-*.tmp")), [])

    def test_hardlink_move_refuses_to_delete_a_replaced_source(self):
        source = self.root / "source.txt"
        destination = self.root / "destination.txt"
        replacement = self.root / "replacement.txt"
        source.write_text("original", encoding="utf-8")
        replacement.write_text("replacement", encoding="utf-8")
        real_link = os.link

        def replace_after_link(src, dst):
            real_link(src, dst)
            os.replace(replacement, src)

        with mock.patch("kira.tools.fileops.os.link", side_effect=replace_after_link):
            with self.assertRaisesRegex(OSError, "source changed"):
                _move_file_no_overwrite(str(source), str(destination))

        self.assertEqual(source.read_text(encoding="utf-8"), "replacement")
        self.assertFalse(destination.exists())

    def test_move_never_overwrites_existing_destination(self):
        source = self.root / "source.txt"
        destination = self.root / "destination.txt"
        source.write_text("source", encoding="utf-8")
        destination.write_text("destination", encoding="utf-8")

        with self.assertRaises(FileExistsError):
            _move_file_no_overwrite(str(source), str(destination))

        self.assertEqual(source.read_text(encoding="utf-8"), "source")
        self.assertEqual(destination.read_text(encoding="utf-8"), "destination")


if __name__ == "__main__":
    unittest.main()
